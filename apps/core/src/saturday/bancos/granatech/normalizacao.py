"""Tradução das respostas da Granatech para o vocabulário do Saturday.

Só os campos descritos no AGENTS.md são lidos (regra 12). O detalhe da
consulta é guardado no banco no formato da própria API, mas recortado a esses
campos (``recortar_detalhe``): o mesmo ``normalizar_detalhe`` lê a resposta
da API e a cópia gravada.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from saturday.bancos.granatech.numeros import decimal_de, decimal_ou_none

CAMPOS_PRODUTO = (
    "id",
    "nome",
    "parcelas",
    "taxa_mensal",
    "seguro",
    "margem",
    "limite_minimo",
    "limite_maximo",
    "id_empresa_seguro",
    "id_cobertura_seguro",
)
CAMPOS_MARGEM = (
    "id",
    "margem",
    "nome_empregador",
    "documento_empregador",
    "elegivel_empregador",
)
CAMPOS_PESSOA = (
    "name",
    "document",
    "birth_date",
    "age",
    "gender",
    "mother_name",
    "civil_status",
    "email",
    "phone_number",
)
CAMPOS_ENDERECO = (
    "zip_code",
    "address_name",
    "number",
    "complement",
    "district",
    "city",
    "uf",
)


@dataclass(frozen=True)
class Endereco:
    cep: str
    logradouro: str
    numero: str
    complemento: str
    bairro: str
    cidade: str
    uf: str


@dataclass(frozen=True)
class Pessoa:
    nome: str
    cpf: str
    nascimento: date | None
    idade: int | None
    sexo: str | None
    nome_mae: str | None
    estado_civil: str | None
    email: str | None
    telefone: str | None
    endereco: Endereco | None


@dataclass(frozen=True)
class Produto:
    id: str
    nome: str
    parcelas: tuple[int, ...]
    taxa_mensal: Decimal
    seguro: bool
    margem: Decimal | None
    limite_minimo: Decimal | None
    limite_maximo: Decimal | None
    id_empresa_seguro: str | None
    # `id_cobertura_seguro` na consulta; vai como `id_produto_seguro` na simulação.
    id_produto_seguro: str | None


@dataclass(frozen=True)
class Vinculo:
    id_margem: str
    margem: Decimal
    nome_empregador: str
    documento_empregador: str
    elegivel_empregador: bool
    produtos: tuple[Produto, ...]


@dataclass(frozen=True)
class DetalheConsulta:
    id: str
    vinculos: tuple[Vinculo, ...]
    pessoa: Pessoa | None


@dataclass(frozen=True)
class Simulacao:
    liberado: Decimal
    valor_parcela: Decimal
    numero_parcelas: int
    taxa_mensal: Decimal
    taxa_anual: Decimal | None
    cet_mensal: Decimal
    cet_anual: Decimal | None
    valor_iof: Decimal
    valor_seguro: Decimal
    valor_total_financiado: Decimal
    valor_total_divida: Decimal
    primeiro_vencimento: date | None
    id_empregador: str | None
    info_seguradora: dict[str, Any]
    # O bloco que voltou, não o pedido: na dev, `seguro=false` é ignorado.
    seguro_aplicado: bool
    limitado_ao_teto: bool = False


# ------------------------------------------------------------------ consulta


def _texto(valor: object) -> str:
    return "" if valor is None else str(valor)


def _texto_ou_none(valor: object) -> str | None:
    return None if valor is None or valor == "" else str(valor)


def _data(valor: object) -> date | None:
    if not isinstance(valor, str) or not valor:
        return None
    try:
        return date.fromisoformat(valor[:10])
    except ValueError:
        return None


def _parcelas(valor: object) -> tuple[int, ...]:
    if isinstance(valor, list):
        return tuple(int(v) for v in valor)
    if valor is None or valor == "":
        return ()
    return (int(str(valor)),)


def _produto(dados: dict[str, Any]) -> Produto:
    return Produto(
        id=_texto(dados.get("id")),
        nome=_texto(dados.get("nome")),
        parcelas=_parcelas(dados.get("parcelas")),
        taxa_mensal=decimal_de(dados.get("taxa_mensal")),
        seguro=bool(dados.get("seguro")),
        margem=decimal_ou_none(dados.get("margem")),
        limite_minimo=decimal_ou_none(dados.get("limite_minimo")),
        limite_maximo=decimal_ou_none(dados.get("limite_maximo")),
        id_empresa_seguro=_texto_ou_none(dados.get("id_empresa_seguro")),
        id_produto_seguro=_texto_ou_none(dados.get("id_cobertura_seguro")),
    )


def _vinculo(dados: dict[str, Any]) -> Vinculo:
    return Vinculo(
        id_margem=_texto(dados.get("id")),
        margem=decimal_de(dados.get("margem")),
        nome_empregador=_texto(dados.get("nome_empregador")),
        documento_empregador=_texto(dados.get("documento_empregador")),
        elegivel_empregador=bool(dados.get("elegivel_empregador")),
        produtos=tuple(_produto(p) for p in dados.get("produtos") or [] if isinstance(p, dict)),
    )


def _pessoa(dados: dict[str, Any]) -> Pessoa:
    endereco = dados.get("address")
    idade = dados.get("age")
    return Pessoa(
        nome=_texto(dados.get("name")),
        cpf=_texto(dados.get("document")),
        nascimento=_data(dados.get("birth_date")),
        idade=int(idade) if isinstance(idade, int | str) and str(idade).isdigit() else None,
        sexo=_texto_ou_none(dados.get("gender")),
        nome_mae=_texto_ou_none(dados.get("mother_name")),
        estado_civil=_texto_ou_none(dados.get("civil_status")),
        email=_texto_ou_none(dados.get("email")),
        telefone=_texto_ou_none(dados.get("phone_number")),
        endereco=None
        if not isinstance(endereco, dict)
        else Endereco(
            cep=_texto(endereco.get("zip_code")),
            logradouro=_texto(endereco.get("address_name")),
            numero=_texto(endereco.get("number")),
            complemento=_texto(endereco.get("complement")),
            bairro=_texto(endereco.get("district")),
            cidade=_texto(endereco.get("city")),
            uf=_texto(endereco.get("uf")),
        ),
    )


def normalizar_detalhe(dados: dict[str, Any]) -> DetalheConsulta | None:
    """Detalhe da consulta, ou ``None`` se ainda não está pronto (sem margens)."""

    margens = [m for m in dados.get("margens") or [] if isinstance(m, dict)]
    if not margens:
        return None
    pessoa = dados.get("pessoa_natural")
    return DetalheConsulta(
        id=_texto(dados.get("id")),
        vinculos=tuple(_vinculo(m) for m in margens),
        pessoa=_pessoa(pessoa) if isinstance(pessoa, dict) else None,
    )


def _recorte(dados: object, campos: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(dados, dict):
        return {}
    return {campo: dados[campo] for campo in campos if campo in dados}


def recortar_detalhe(dados: dict[str, Any]) -> dict[str, Any]:
    """Cópia do detalhe só com os campos do contrato, para gravar no banco."""

    margens = []
    for margem in dados.get("margens") or []:
        recorte = _recorte(margem, CAMPOS_MARGEM)
        recorte["produtos"] = [
            _recorte(p, CAMPOS_PRODUTO) for p in (margem or {}).get("produtos") or []
        ]
        margens.append(recorte)
    pessoa = dados.get("pessoa_natural")
    recorte_pessoa = None
    if isinstance(pessoa, dict):
        recorte_pessoa = _recorte(pessoa, CAMPOS_PESSOA)
        if isinstance(pessoa.get("address"), dict):
            recorte_pessoa["address"] = _recorte(pessoa["address"], CAMPOS_ENDERECO)
    return {"id": dados.get("id"), "margens": margens, "pessoa_natural": recorte_pessoa}


# ------------------------------------------------------------------ simulação


def normalizar_simulacao(dados: dict[str, Any]) -> Simulacao:
    """Lê o bloco que voltou; com os dois, prefere o com seguro (o pedido padrão)."""

    com_seguro = dados.get("resultado_da_simulacao_com_seguro")
    sem_seguro = dados.get("resultado_da_simulacao_sem_seguro")
    if isinstance(com_seguro, dict) and com_seguro:
        bloco, seguro = com_seguro, True
    elif isinstance(sem_seguro, dict) and sem_seguro:
        bloco, seguro = sem_seguro, False
    else:
        raise ValueError("simulação sem resultado")

    parcelas = bloco.get("parcelas")
    vencimento = None
    if isinstance(parcelas, list) and parcelas and isinstance(parcelas[0], dict):
        vencimento = _data(parcelas[0].get("dt_vencimento"))
    info = bloco.get("info_seguradora")

    return Simulacao(
        liberado=decimal_de(bloco.get("valor_solicitado")),
        valor_parcela=decimal_de(bloco.get("valor_parcela")),
        numero_parcelas=int(str(bloco.get("numero_parcelas"))),
        taxa_mensal=decimal_de(bloco.get("taxa_mensal")),
        taxa_anual=decimal_ou_none(bloco.get("taxa_anual")),
        cet_mensal=decimal_de(bloco.get("cet_mensal")),
        cet_anual=decimal_ou_none(bloco.get("cet_anual")),
        valor_iof=decimal_de(bloco.get("valor_iof") or 0),
        valor_seguro=decimal_de(bloco.get("valor_seguro") or 0),
        valor_total_financiado=decimal_de(bloco.get("valor_total_financiado")),
        valor_total_divida=decimal_de(bloco.get("valor_total_divida")),
        primeiro_vencimento=vencimento,
        id_empregador=_texto_ou_none(bloco.get("id_empregador")),
        info_seguradora=info if isinstance(info, dict) else {},
        seguro_aplicado=seguro,
    )


# ------------------------------------------------------------------ proposta e listagens


def itens_da_listagem(dados: object) -> list[dict[str, Any]]:
    """Itens de uma listagem paginada.

    TODO(granatech): formato real das listagens; aceita lista pura ou um
    objeto com `data`, `dados`, `items` ou `content`.
    """

    if isinstance(dados, list):
        return [i for i in dados if isinstance(i, dict)]
    if isinstance(dados, dict):
        for chave in ("data", "dados", "items", "content"):
            valor = dados.get(chave)
            if isinstance(valor, list):
                return [i for i in valor if isinstance(i, dict)]
    return []


def id_da_proposta(dados: object) -> str | None:
    """Id da proposta na resposta do ``POST /propostas``.

    A api-dev devolve só o id, como texto JSON (``"29ee4653-..."``, rodada 10 da
    homologação, 2026-11-13). TODO(granatech): confirmar; aceita também `id`,
    `id_proposta` ou `data.id` num objeto.
    """

    if isinstance(dados, str):
        return dados.strip() or None
    if not isinstance(dados, dict):
        return None
    for valor in (dados.get("id"), dados.get("id_proposta")):
        if valor:
            return str(valor)
    interno = dados.get("data")
    if isinstance(interno, dict) and interno.get("id"):
        return str(interno["id"])
    return None


def _numero(valor: Decimal) -> float:
    # A API recebe número JSON; o Decimal só vira float na borda.
    return float(valor)


def montar_corpo_proposta(
    *,
    id_consulta: str,
    vinculo: Vinculo,
    produto: Produto,
    simulacao: Simulacao,
    tipo_empregador: int,
) -> dict[str, Any]:
    """Corpo do ``POST /propostas`` a partir da simulação aceita.

    Na api-dev, ``informacaoDeSeguros`` é obrigatório em produto com seguro
    (rodada 9 da homologação) e ``id_externo`` precisa ser número: o
    ``"SM-100000820-4"`` da simulação dá 400 (rodada 7). Vai o
    ``id_cobertura_seguro`` do produto (o ``id_produto_seguro`` da simulação),
    como número, aceito nas rodadas 10, 11 e 13.
    """

    financeiro = {
        # TODO(granatech): confirmar `tipo_empregador` (padrão 1 por config).
        "tipo_empregador": tipo_empregador,
        "documento_empregador": vinculo.documento_empregador,
        "valor_solicitado": _numero(simulacao.liberado),
        "valor_total_financiado": _numero(simulacao.valor_total_financiado),
        "valor_parcela": _numero(simulacao.valor_parcela),
        "numero_parcelas": simulacao.numero_parcelas,
        "taxa_mensal": _numero(simulacao.taxa_mensal),
        "valor_seguro": _numero(simulacao.valor_seguro),
        "valor_liberado_habilitado": True,
        "cet_anual": None if simulacao.cet_anual is None else _numero(simulacao.cet_anual),
        "cet_mensal": _numero(simulacao.cet_mensal),
        "valor_iof": _numero(simulacao.valor_iof),
        "taxa_anual": None if simulacao.taxa_anual is None else _numero(simulacao.taxa_anual),
    }
    corpo: dict[str, Any] = {
        "id_empregador": simulacao.id_empregador,
        "id_consulta": id_consulta,
        "id_produto": produto.id,
        "id_margem": vinculo.id_margem,
        "informacoesFinanceira": [financeiro],
    }
    # TODO(granatech): confirmar que `informacaoDeSeguros.id_externo` é o
    # `id_cobertura_seguro` (pergunta enviada em 2026-11-13). Sem cobertura
    # numérica, sobra o `id_externo` da simulação, que a api-dev recusa.
    if simulacao.seguro_aplicado:
        cobertura = produto.id_produto_seguro
        id_externo: int | str = (
            int(cobertura)
            if cobertura and cobertura.isdigit()
            else str(simulacao.info_seguradora.get("id_externo") or "")
        )
        corpo["informacaoDeSeguros"] = {
            "id_empresa_seguradora": produto.id_empresa_seguro,
            "valor_total_financiado": _numero(simulacao.valor_total_financiado),
            "numero_parcelas": simulacao.numero_parcelas,
            "id_externo": id_externo,
            "valor_seguro": _numero(simulacao.valor_seguro),
            "iof": _numero(simulacao.valor_iof),
        }
    # TODO(granatech): `informacaoDeSeguros` de uma proposta sem seguro.
    return corpo


def montar_dados_tomador(
    *,
    pessoa: Pessoa,
    cpf: str,
    nome: str,
    estado_civil: str,
    celular: str,
    conta: dict[str, str],
) -> dict[str, Any]:
    """Corpo do ``POST /propostas/{id}/dados-tomador``.

    Mãe, nascimento e endereço vêm da Granatech (confirmados pelo cliente); nome,
    estado civil, celular e conta vêm da conversa. ``conta`` traz ``banco_codigo``,
    ``agencia``, ``digito_agencia``, ``numero_conta``, ``digito_conta`` e
    ``tipo_conta`` (``conta_corrente`` ou ``conta_poupanca``).
    """

    endereco = pessoa.endereco
    return {
        "nome_completo": nome,
        # TODO(granatech): valores aceitos de `estado_civil` (enviamos em maiúsculas).
        "estado_civil": estado_civil,
        # A api-dev pede "Date instance" (400 com só a data); o exemplo da collection
        # de contratação manda meia-noite UTC.
        "data_nascimento": (
            f"{pessoa.nascimento.isoformat()}T00:00:00.000Z" if pessoa.nascimento else None
        ),
        "telefone_endereco": celular,
        "nome_completo_mae": pessoa.nome_mae,
        "cep": endereco.cep if endereco else None,
        "endereco": endereco.logradouro if endereco else None,
        "numero_endereco": endereco.numero if endereco else None,
        "bairro": endereco.bairro if endereco else None,
        "cidade": endereco.cidade if endereco else None,
        "estado": endereco.uf if endereco else None,
        "complemento": endereco.complemento if endereco else "",
        "cpf": cpf,
        "tipo_dados_bancarios": "dados_bancarios",
        "banco_detalhe": {
            "agencia": conta["agencia"],
            "digito_agencia": conta.get("digito_agencia", ""),
            "numero_conta": conta["numero_conta"],
            "digito_conta": conta["digito_conta"],
            "tipo_conta": conta["tipo_conta"],
            "banco_codigo": conta["banco_codigo"],
        },
    }
