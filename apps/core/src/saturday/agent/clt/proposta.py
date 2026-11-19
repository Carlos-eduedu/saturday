"""Proposta e pós-venda do ramo CLT (Fase 6).

Etapas: ``dados_proposta`` → ``aceite`` → ``proposta`` → ``formalizacao`` →
``pago``, com ``encerrada`` (reprovada ou cancelada), ``nova_conta`` (depois de
uma falha de pagamento) e handoff. Os dados vêm antes do SIM
(docs/decisoes/0008): o SIM autoriza exatamente os valores e a conta que vão
para o banco.

Os eventos da proposta chegam como turno de sistema ``proposta:<acao>``; a ação
sai de ``bancos.granatech.status.acao_da_proposta``.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from saturday.agent.clt import leitura
from saturday.agent.clt.mensagens import Fixo, texto, versao
from saturday.agent.clt.turno import Turno, reais
from saturday.bancos.granatech.cliente import ErroGranatech, ErroIncerto
from saturday.bancos.granatech.normalizacao import (
    DetalheConsulta,
    Endereco,
    Pessoa,
    Simulacao,
    montar_corpo_proposta,
    montar_dados_tomador,
)
from saturday.dados import consentimentos, links
from saturday.dados.modelos import Conversa
from saturday.dados.sessao import sessao as abrir_sessao

logger = logging.getLogger("saturday.agent.clt.nos")

CONSENTIMENTO_PROPOSTA = "proposta"
# Etapas em que a jornada espera um evento do banco.
AGUARDANDO = frozenset({"proposta", "formalizacao"})
# Endereço informado pelo cliente: os quatro primeiros não podem ficar vazios.
CAMPOS_ENDERECO = ("logradouro", "bairro", "cidade", "uf", "numero", "complemento")
PASSOS_CONTA = ("banco", "banco_lista", "tipo_conta", "agencia", "conta", "titular")
MOTIVO_CANCELAMENTO_MAX = 200


# ---------------------------------------------------------------- apoio


def _detalhe(t: Turno) -> DetalheConsulta:
    _, _, detalhe = t.granatech.situacao(str(t.clt["consulta"]))
    if detalhe is None:
        raise RuntimeError("consulta sem detalhe gravado")
    return detalhe


def _pessoa(t: Turno) -> Pessoa | None:
    """O tomador da Granatech, com a mãe e o endereço que o cliente informou.

    O que o cliente informa vale sobre o da Granatech: ele só informa quando ela
    não devolveu ou quando ele disse que o dela está errado (decisão 0034).
    """

    pessoa = _detalhe(t).pessoa
    if pessoa is None:
        return None
    endereco = t.dados.get("endereco")
    return replace(
        pessoa,
        nome_mae=t.dados.get("mae") or pessoa.nome_mae,
        endereco=Endereco(**endereco) if endereco else pessoa.endereco,
    )


def _tomador_completo(t: Turno, pessoa: Pessoa | None) -> bool:
    """Nascimento, mãe e endereço: sem um deles o banco recusa os dados do tomador.

    O nascimento que a Granatech não devolver é o que o cliente informou na
    identificação; a mãe e o endereço que faltarem, o cliente informa nos dados
    da proposta.
    """

    return (
        pessoa is not None
        and bool(pessoa.nome_mae)
        and pessoa.endereco is not None
        and (pessoa.nascimento is not None or bool(t.dados.get("nascimento")))
    )


def _linha_endereco(pessoa: Pessoa) -> str:
    e = pessoa.endereco
    if e is None:
        return ""
    partes = [f"{e.logradouro}, {e.numero}", e.complemento, e.bairro, f"{e.cidade}/{e.uf}"]
    return " - ".join(p for p in partes if p and p.strip(", "))


def simulacao(oferta: dict[str, Any]) -> Simulacao:
    """A oferta guardada no checkpoint (texto) de volta a ``Simulacao``."""

    def dec(chave: str) -> Decimal:
        return Decimal(str(oferta[chave]))

    def dec_ou_none(chave: str) -> Decimal | None:
        return None if oferta.get(chave) in (None, "None") else dec(chave)

    vencimento = oferta.get("primeiro_vencimento")
    return Simulacao(
        liberado=dec("liberado"),
        valor_parcela=dec("valor_parcela"),
        numero_parcelas=int(oferta["numero_parcelas"]),
        taxa_mensal=dec("taxa_mensal"),
        taxa_anual=dec_ou_none("taxa_anual"),
        cet_mensal=dec("cet_mensal"),
        cet_anual=dec_ou_none("cet_anual"),
        valor_iof=dec("valor_iof"),
        valor_seguro=dec("valor_seguro"),
        valor_total_financiado=dec("valor_total_financiado"),
        valor_total_divida=dec("valor_total_divida"),
        primeiro_vencimento=date.fromisoformat(vencimento) if vencimento else None,
        id_empregador=oferta.get("id_empregador"),
        info_seguradora=dict(oferta.get("info_seguradora") or {}),
        seguro_aplicado=bool(oferta.get("seguro_aplicado")),
        limitado_ao_teto=bool(oferta.get("limitado_ao_teto")),
    )


def _conta_mascarada(conta: dict[str, str]) -> str:
    numero = f"{conta['numero_conta']}-{conta['digito_conta']}"
    return f"final {numero[-4:]}"


# ---------------------------------------------------------------- início


def iniciar(t: Turno) -> dict[str, Any]:
    """O cliente quer seguir com a oferta."""

    if not t.granatech.proposta_ativa:
        # Proposta automática desligada: um especialista segue daqui.
        return t.handoff("aceite_clt", texto("aceite"))
    pessoa = _pessoa(t)
    if pessoa is None or not (pessoa.nascimento or t.dados.get("nascimento")):
        return t.handoff("dados_divergentes")
    if not pessoa.nome_mae:
        return t.perguntar("dados_proposta", "mae_informar")
    return t.perguntar("dados_proposta", "mae", mae=pessoa.nome_mae)


def pedir_confirmacao(t: Turno, passo: str) -> dict[str, Any]:
    """A confirmação da mãe ou do endereço outra vez."""

    pessoa = _pessoa(t)
    if pessoa is None:
        return t.handoff("dados_divergentes")
    if passo == "mae":
        return t.perguntar("dados_proposta", passo, mae=pessoa.nome_mae)
    if passo == "endereco_cep":
        novo = t.dados["endereco_novo"]
        return t.perguntar("dados_proposta", passo, endereco=_linha_cep(novo))
    return t.perguntar("dados_proposta", passo, endereco=_linha_endereco(pessoa))


def _depois_da_mae(t: Turno) -> dict[str, Any]:
    pessoa = _pessoa(t)
    if pessoa is None:
        return t.handoff("dados_divergentes")
    if pessoa.endereco is None:
        return t.perguntar("dados_proposta", "cep")
    return t.perguntar("dados_proposta", "endereco", endereco=_linha_endereco(pessoa))


def _linha_cep(novo: dict[str, str]) -> str:
    return f"{novo['logradouro']} - {novo['bairro']} - {novo['cidade']}/{novo['uf']}"


def _proximo_do_endereco(t: Turno) -> dict[str, Any]:
    """Pergunta o primeiro campo que falta; completo, grava e segue."""

    novo = t.dados["endereco_novo"]
    for campo in CAMPOS_ENDERECO:
        if campo not in novo or (campo not in ("numero", "complemento") and not novo[campo]):
            return t.perguntar("dados_proposta", campo)
    t.dados["endereco"] = t.dados.pop("endereco_novo")
    return t.perguntar("dados_proposta", "estado_civil")


def _endereco(t: Turno, passo: str) -> dict[str, Any]:
    """Passos do endereço informado pelo cliente (decisão 0034)."""

    novo = t.dados.get("endereco_novo")
    if passo == "cep":
        cep = leitura.cep(t.texto)
        if cep is None:
            return t.erro("cep_invalido")
        brasilapi = t.contexto.brasilapi
        achado = brasilapi.buscar_cep(cep, conversa_id=t.conversa_id) if brasilapi else None
        t.dados["endereco_novo"] = {"cep": cep, **(achado or {})}
        if achado and all(achado.get(c) for c in CAMPOS_ENDERECO[:4]):
            return t.perguntar("dados_proposta", "endereco_cep", endereco=_linha_cep(achado))
        # CEP sem resposta ou sem rua: o cliente informa o que faltou.
        return _proximo_do_endereco(t)
    if novo is None:
        return t.perguntar("dados_proposta", "cep")
    if passo == "endereco_cep":
        resposta = leitura.sim_ou_nao(t.texto)
        if resposta is None:
            return t.erro("repetir_sim_nao")
        if resposta is False:
            t.dados.pop("endereco_novo")
            return t.perguntar("dados_proposta", "cep")
        return _proximo_do_endereco(t)
    if passo == "uf":
        valor = leitura.uf(t.texto)
        if valor is None:
            return t.erro("uf_invalida")
    elif passo == "numero":
        valor = leitura.numero_endereco(t.texto)
        if valor is None:
            return t.erro("numero_invalido")
    elif passo == "complemento":
        valor = leitura.complemento(t.texto)
    else:
        valor = " ".join(t.texto.split())[:80]
        if len(valor) < 2:
            return t.erro("endereco_invalido")
    novo[passo] = valor
    return _proximo_do_endereco(t)


# ---------------------------------------------------------------- dados da proposta


def dados_proposta(t: Turno) -> dict[str, Any]:
    passo = str(t.clt.get("passo"))
    if passo in ("mae", "endereco"):
        resposta = leitura.sim_ou_nao(t.texto)
        if resposta is None:
            return t.erro("repetir_sim_nao")
        if resposta is False:
            # O cliente corrige o dado da Granatech (decisão 0034).
            if passo == "mae":
                return t.perguntar("dados_proposta", "mae_informar")
            t.dados.pop("endereco", None)
            return t.perguntar("dados_proposta", "cep")
        if passo == "mae":
            return _depois_da_mae(t)
        return t.perguntar("dados_proposta", "estado_civil")
    if passo == "mae_informar":
        mae = leitura.nome_completo(t.texto)
        if mae is None:
            return t.erro("mae_invalida")
        t.dados["mae"] = mae.upper()
        return _depois_da_mae(t)
    if passo in ("cep", "endereco_cep", *CAMPOS_ENDERECO):
        return _endereco(t, passo)
    if passo == "estado_civil":
        estado = leitura.estado_civil(t.texto)
        if estado is None:
            return t.erro("estado_civil_invalido")
        t.dados["estado_civil"] = estado
        return t.perguntar("dados_proposta", "banco")
    return conta(t)


def conta(t: Turno) -> dict[str, Any]:
    """Passos da conta, usados nos dados da proposta e depois de falha de pagamento."""

    etapa = str(t.clt.get("etapa"))
    passo = str(t.clt.get("passo"))
    nova = t.dados.setdefault("conta_nova", {})
    if passo == "banco":
        try:
            bancos = t.granatech.bancos_em_cache()
        except ErroGranatech:
            return t.handoff("granatech_indisponivel")
        candidatos = leitura.bancos_candidatos(t.texto, bancos)
        if not candidatos:
            return t.erro("banco_invalido")
        if len(candidatos) > 1:
            t.clt.update(passo="banco_lista", erros=0)
            t.clt["bancos"] = [
                {"codigo": str(b.get("codigo")), "nome": str(b.get("nome"))} for b in candidatos
            ]
            opcoes = Fixo(
                "\n".join(
                    texto("opcao_banco", numero=i, nome=b["nome"], codigo=b["codigo"])
                    for i, b in enumerate(t.clt["bancos"], start=1)
                ),
                "opcao_banco",
            )
            return t.responder(texto("escolher_banco"), opcoes)
        nova.update(banco_codigo=str(candidatos[0].get("codigo")))
        nova.update(banco_nome=str(candidatos[0].get("nome")))
        return t.perguntar(etapa, "tipo_conta")
    if passo == "banco_lista":
        escolhas = list(t.clt.get("bancos") or [])
        indice = leitura.numero_da_lista(t.texto, len(escolhas))
        if indice is None:
            return t.erro("banco_lista_invalida")
        nova.update(banco_codigo=escolhas[indice]["codigo"], banco_nome=escolhas[indice]["nome"])
        return t.perguntar(etapa, "tipo_conta")
    if passo == "tipo_conta":
        tipo = leitura.tipo_conta(t.texto)
        if tipo is None:
            return t.erro("tipo_conta_invalido")
        nova["tipo_conta"] = tipo
        return t.perguntar(etapa, "agencia")
    if passo == "agencia":
        lida = leitura.agencia(t.texto)
        if lida is None:
            return t.erro("agencia_invalida")
        nova.update(agencia=lida[0], digito_agencia=lida[1])
        return t.perguntar(etapa, "conta")
    if passo == "conta":
        lida = leitura.conta_com_digito(t.texto)
        if lida is None:
            return t.erro("conta_invalida")
        nova.update(numero_conta=lida[0], digito_conta=lida[1])
        return t.perguntar(etapa, "titular")

    resposta = leitura.sim_ou_nao(t.texto)
    if resposta is None:
        return t.erro("repetir_sim_nao")
    if resposta is False:
        t.dados["conta_nova"] = {}
        return t.perguntar(etapa, "banco", texto("conta_de_terceiro"))
    t.dados["conta"] = t.dados.pop("conta_nova")
    if etapa == "nova_conta":
        return _conta_corrigida(t)
    return pedir_aceite(t)


# ---------------------------------------------------------------- aceite


def pedir_aceite(t: Turno) -> dict[str, Any]:
    oferta = simulacao(t.clt["oferta"])
    conta_ = t.dados["conta"]
    resumo = texto(
        "resumo_aceite",
        liberado=reais(oferta.liberado),
        conta=_conta_mascarada(conta_),
        banco=conta_["banco_nome"],
        n=oferta.numero_parcelas,
        parcela=reais(oferta.valor_parcela),
        taxa=reais(oferta.taxa_mensal),
        cet=reais(oferta.cet_mensal),
        seguro=reais(oferta.valor_seguro),
    )
    # O texto exato vai para a prova do SIM.
    t.clt.update(etapa="aceite", passo="sim", erros=0, resumo=str(resumo))
    return t.responder(resumo)


def aceite(t: Turno) -> dict[str, Any]:
    if leitura.consentiu(t.texto) or t.aceite_de_teste():
        return _criar_proposta(t)
    if leitura.NEGACAO.search(t.texto) or leitura.pedido_de_mudanca(t.texto):
        t.clt.update(etapa="oferta", passo=None, erros=0)
        t.clt.pop("resumo", None)
        return t.responder(texto("aceite_recusado"))
    if leitura.eh_pergunta(t.texto):
        return t.faq()
    return t.responder(texto("repetir_aceite"))


def _criar_proposta(t: Turno) -> dict[str, Any]:
    if not _tomador_completo(t, _pessoa(t)):
        # De novo, antes da prova, da intenção e do POST: a ficha pode ter mudado
        # desde o começo dos dados. Proposta sem os dados do tomador não nasce.
        return t.handoff("dados_divergentes")
    fabrica = t.contexto.fabrica
    consentimentos.gravar_prova(
        fabrica,
        conversa_id=t.conversa_id,
        tipo=CONSENTIMENTO_PROPOSTA,
        texto_mostrado=str(t.clt["resumo"]),
        versao=versao(),
        resposta_literal=t.resposta_da_prova(),
        wamid=t.state.get("message_id"),
        cpf=t.dados["cpf"],
    )
    return seguir_proposta(t)


def seguir_proposta(t: Turno) -> dict[str, Any]:
    """Cria (ou reencontra) a proposta e envia os dados do tomador.

    Depois do SIM gravado, ou pelo painel ao reconciliar uma proposta incerta:
    ``criar_proposta`` nunca repete um POST incerto, só procura na listagem.
    """

    detalhe = _detalhe(t)
    oferta = t.clt["oferta"]
    vinculo = next(v for v in detalhe.vinculos if v.id_margem == oferta["id_margem"])
    produto = next(p for p in vinculo.produtos if p.id == oferta["id_produto"])
    corpo = montar_corpo_proposta(
        id_consulta=str(t.clt["consulta"]),
        vinculo=vinculo,
        produto=produto,
        simulacao=simulacao(oferta),
    )
    try:
        id_proposta = t.granatech.criar_proposta(
            consulta_id=t.granatech.id_local_da_consulta(str(t.clt["consulta"])),
            corpo=corpo,
            conversa_id=t.conversa_id,
            condicoes=dict(oferta),
        )
    except ErroIncerto:
        # Regra 4: nunca um segundo POST automático.
        return t.handoff("proposta_incerta")
    except ErroGranatech:
        return t.handoff("granatech_indisponivel")

    t.clt.update(etapa="proposta", passo=None, erros=0, proposta=id_proposta)
    pessoa = _pessoa(t)
    if pessoa is None:
        return t.handoff("dados_divergentes")
    tomador = montar_dados_tomador(
        pessoa=pessoa,
        nascimento=t.dados.get("nascimento"),
        cpf=t.dados["cpf"],
        nome=t.dados["nome"],
        estado_civil=t.dados["estado_civil"],
        celular=t.dados["celular"],
        conta=t.dados["conta"],
    )
    try:
        t.granatech.enviar_dados_tomador(id_proposta, tomador, conversa_id=t.conversa_id)
    except ErroGranatech:
        # A proposta existe; um atendente completa os dados no banco.
        return t.handoff("dados_tomador_falhou")
    return t.responder(texto("proposta_enviada"))


# ---------------------------------------------------------------- esperando o banco


def aguardando(t: Turno) -> dict[str, Any]:
    if leitura.pediu_cancelamento(t.texto):
        return t.handoff("pediu_cancelamento")
    if leitura.eh_pergunta(t.texto):
        return t.faq()
    return t.responder(texto("acompanhando"))


def _conta_corrigida(t: Turno) -> dict[str, Any]:
    conta_ = t.dados["conta"]
    if not t.granatech.dados_bancarios_ativo:
        # PATCH desligado neste ambiente: a equipe corrige no banco.
        t.clt.update(etapa="proposta", passo=None, erros=0)
        return t.handoff("falha_pagamento", detalhe={"conta": conta_})
    detalhe = {k: v for k, v in conta_.items() if k != "banco_nome"}
    try:
        t.granatech.corrigir_dados_bancarios(
            str(t.clt["proposta"]), detalhe, conversa_id=t.conversa_id
        )
    except ErroGranatech:
        return t.handoff("falha_pagamento", detalhe={"conta": conta_})
    t.clt.update(etapa="proposta", passo=None, erros=0)
    return t.responder(texto("conta_corrigida"))


# ---------------------------------------------------------------- eventos da proposta


def _link(t: Turno) -> tuple[str, str] | None:
    """Endereço e código do link curto da biometria (um por proposta)."""

    fabrica = t.contexto.fabrica
    if not t.contexto.dominio_publico:
        return None
    codigo = t.clt.get("link")
    if not codigo:
        try:
            url = t.granatech.status_proposta(str(t.clt["proposta"])).get(
                "url_seguranca_identidade"
            )
        except ErroGranatech:
            return None
        if not isinstance(url, str) or not url.startswith("https://"):
            return None
        with abrir_sessao(fabrica) as sessao:
            codigo = links.criar(
                sessao, id_proposta=str(t.clt["proposta"]), url=url, teste=t.granatech.teste
            )
        t.clt["link"] = codigo
    return links.endereco(t.contexto.dominio_publico, str(codigo)), str(codigo)


def _informacoes(t: Turno) -> Any:
    historico = t.granatech.historico_proposta(str(t.clt["proposta"]))
    return historico[-1].get("informacoes") if historico else None


def _aviso(t: Turno, chave: str, modelo: str, **valores: object) -> dict[str, Any]:
    saida = t.responder(texto(chave, **valores))
    saida["modelo_aviso"] = modelo
    return saida


def evento(t: Turno, acao: str) -> dict[str, Any]:
    if not t.clt.get("proposta"):
        return t.responder()
    if acao == "silencio":
        return t.responder()
    if acao == "criada":
        return _aviso(t, "aviso_criada", "atualizacao_pedido")
    if acao in ("formalizar", "refazer"):
        link = _link(t)
        if link is None:
            return t.handoff("link_indisponivel")
        t.clt.update(etapa="formalizacao", passo=None)
        chave, modelo = (
            ("aviso_formalizar", "assinatura_pronta")
            if acao == "formalizar"
            else ("aviso_refazer", "assinatura_refazer")
        )
        saida = _aviso(t, chave, modelo, link=link[0])
        saida["link_aviso"] = link[1]
        return saida
    if acao == "analise":
        return _aviso(t, "aviso_analise", "atualizacao_pedido")
    if acao == "identidade_ok":
        t.clt.update(etapa="proposta", passo=None)
        return _aviso(t, "aviso_identidade_ok", "atualizacao_pedido")
    if acao == "revisao":
        return t.handoff("revisao_banco", detalhe={"informacoes": _informacoes(t)})
    if acao == "falha_pagamento":
        falhas = int(t.clt.get("falhas_pagamento") or 0) + 1
        t.clt["falhas_pagamento"] = falhas
        if falhas >= 2:
            return t.handoff("falha_pagamento_repetida")
        t.dados["conta_nova"] = {}
        t.clt.update(etapa="nova_conta", passo="banco", erros=0)
        saida = t.responder(texto("aviso_falha_pagamento"), texto("pedir_banco"))
        saida["modelo_aviso"] = "dados_bancarios_pendentes"
        return saida
    if acao == "reprovada":
        t.clt.update(etapa="encerrada", passo=None)
        return _aviso(t, "aviso_reprovada", "atualizacao_pedido")
    if acao == "cancelada":
        t.clt.update(etapa="encerrada", passo=None)
        motivo = _informacoes(t)
        if isinstance(motivo, str) and 0 < len(motivo.strip()) <= MOTIVO_CANCELAMENTO_MAX:
            return _aviso(t, "aviso_cancelada_motivo", "atualizacao_pedido", motivo=motivo)
        return _aviso(t, "aviso_cancelada", "atualizacao_pedido")
    if acao == "paga":
        t.clt.update(etapa="pago", passo=None)
        return _aviso(t, "aviso_paga", "pagamento_confirmado")
    return t.handoff("status_desconhecido", detalhe={"acao": acao})


# ---------------------------------------------------------------- marketing


def marketing(t: Turno) -> str | None:
    fabrica, conversa_id = t.contexto.fabrica, t.conversa_id
    if conversa_id is None:
        return None
    with abrir_sessao(fabrica) as sessao:
        return sessao.scalar(select(Conversa.marketing).where(Conversa.id == conversa_id))


def gravar_marketing(t: Turno, valor: str) -> None:
    """Opt-in/opt-out: quem grava é o serviço, na transação do turno.

    A linha da conversa está travada pelo próprio turno; uma sessão à parte
    esperaria por ela para sempre.
    """

    t.marketing = valor
