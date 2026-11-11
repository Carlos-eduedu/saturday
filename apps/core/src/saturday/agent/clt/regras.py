"""Regras do Crédito do Trabalhador que não dependem de rede.

Idade × prazo, recontato por tempo de casa, escolha de vínculo e de produto e a
checagem da empresa pela BrasilAPI. Tudo determinístico e testado.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Any

from saturday.agent.clt.leitura import normalizar
from saturday.bancos.granatech.normalizacao import DetalheConsulta, Produto, Vinculo

PRAZOS = (17, 25, 36, 48)
IDADE_MINIMA = 21
LIMITE_IDADE = {"F": 57, "M": 62}
TEMPO_DE_CASA_MESES = 12
EMPRESA_IDADE_MINIMA_MESES = 24
MAX_NOVAS_SIMULACOES = 5

# Comissão da MEX por produto: decide qual oferecer.
COMISSAO_CMR48 = Decimal("7")
COMISSAO_COM_SEGURO = Decimal("4")
COMISSAO_SEM_SEGURO = Decimal("0.5")

_SITUACOES_RUINS = (
    "recuperacao judicial",
    "recuperacao extrajudicial",
    "falencia",
    "falida",
    "massa falida",
    "liquidacao",
)


def somar_meses(dia: date, meses: int) -> date:
    total = dia.month - 1 + meses
    ano, mes = dia.year + total // 12, total % 12 + 1
    return date(ano, mes, min(dia.day, calendar.monthrange(ano, mes)[1]))


def idade(nascimento: date, hoje: date) -> int:
    return (
        hoje.year - nascimento.year - ((hoje.month, hoje.day) < (nascimento.month, nascimento.day))
    )


def prazos_permitidos(nascimento: date, sexo: str, hoje: date) -> tuple[int, ...]:
    """Prazos que terminam antes do limite de idade (57 mulher, 62 homem).

    Um prazo P vale se ``nascimento + limite`` cai depois de ``hoje + P meses``.
    Abaixo de 21 anos, nenhum.
    """

    if idade(nascimento, hoje) < IDADE_MINIMA or sexo not in LIMITE_IDADE:
        return ()
    limite = somar_meses(nascimento, LIMITE_IDADE[sexo] * 12)
    return tuple(p for p in PRAZOS if limite > somar_meses(hoje, p))


def data_recontato_tempo_casa(meses_de_casa: int, hoje: date) -> date:
    return somar_meses(hoje, TEMPO_DE_CASA_MESES - meses_de_casa)


# ---------------------------------------------------------------- vínculo e produto


def vinculos_ofertaveis(detalhe: DetalheConsulta) -> list[Vinculo]:
    return [v for v in detalhe.vinculos if v.elegivel_empregador and v.margem > 0]


def comissao(produto: Produto) -> Decimal:
    if produto.nome.upper().startswith("CMR48") or produto.id.upper() == "CMR48":
        return COMISSAO_CMR48
    return COMISSAO_COM_SEGURO if produto.seguro else COMISSAO_SEM_SEGURO


def _opcoes(vinculo: Vinculo, prazos: Iterable[int], sem_seguro: bool) -> list[tuple[Produto, int]]:
    permitidos = set(prazos)
    opcoes = []
    for produto in vinculo.produtos:
        if sem_seguro and produto.seguro:
            continue
        validos = [p for p in produto.parcelas if p in permitidos]
        if validos:
            opcoes.append((produto, max(validos)))
    return opcoes


def escolher_produto(
    vinculo: Vinculo,
    prazos: Iterable[int],
    *,
    sem_seguro: bool = False,
    prazo_desejado: int | None = None,
) -> tuple[Produto, int] | None:
    """Produto e prazo a simular.

    Sem pedido do cliente: o de maior comissão (empate: o prazo mais longo).
    Com ``prazo_desejado``: o prazo permitido mais próximo, e entre os produtos
    desse prazo o de maior comissão. ``sem_seguro`` restringe aos sem seguro.
    """

    opcoes = _opcoes(vinculo, prazos, sem_seguro)
    if not opcoes:
        return None
    if prazo_desejado is not None:
        alvo = min({p for _, p in opcoes}, key=lambda p: (abs(p - prazo_desejado), -p))
        opcoes = [(produto, p) for produto, p in opcoes if p == alvo]
    return max(opcoes, key=lambda op: (comissao(op[0]), op[1]))


def prazos_disponiveis(vinculo: Vinculo, prazos: Iterable[int], sem_seguro: bool) -> list[int]:
    return sorted({p for _, p in _opcoes(vinculo, prazos, sem_seguro)})


# ---------------------------------------------------------------- empresa


def _meses_entre(inicio: date, fim: date) -> int:
    return (fim.year - inicio.year) * 12 + fim.month - inicio.month - (fim.day < inicio.day)


def empresa_reprovada(dados: dict[str, Any], hoje: date) -> str | None:
    """Motivo da reprovação da empresa pela BrasilAPI, ou ``None`` se passa."""

    situacao = normalizar(str(dados.get("descricao_situacao_cadastral") or ""))
    if situacao != "ativa":
        return "situacao_cadastral"
    try:
        inicio = date.fromisoformat(str(dados.get("data_inicio_atividade") or ""))
    except ValueError:
        return "data_inicio_atividade"
    if _meses_entre(inicio, hoje) < EMPRESA_IDADE_MINIMA_MESES:
        return "empresa_nova"
    if dados.get("opcao_pelo_mei") is True:
        return "mei"
    if str(dados.get("codigo_porte")) == "1":
        return "microempresa"
    razao = normalizar(str(dados.get("razao_social") or ""))
    if any(trecho in razao for trecho in _SITUACOES_RUINS):
        return "situacao_juridica"
    return None
