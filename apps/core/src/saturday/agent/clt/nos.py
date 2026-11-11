"""Nó do ramo CLT: uma função por etapa, escolhida por ``clt.etapa``.

Etapas (docs/decisoes/0007): ``triagem`` → ``empresa`` → ``identificacao`` →
``consentimento`` → ``consultando`` → ``escolha_vinculo`` → ``oferta``, com as
saídas ``nao_elegivel``, ``recontato`` e handoff. Cada resposta de cliente é lida
em código (``leitura``); o que não é reconhecido e parece pergunta vai para a
FAQ sem mudar a etapa. Os textos saem de ``conhecimento/clt/mensagens.yaml``.

Turnos de sistema (``evento_sistema``) chegam sem mensagem do cliente: consulta
pronta, consulta sem margem ou com erro, termo pendente e recontato.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Callable
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from langgraph.runtime import Runtime

from saturday.agent.clt import leitura, proposta, regras
from saturday.agent.clt.mensagens import chaves, texto, variaveis, versao
from saturday.agent.clt.turno import PERGUNTAS, Turno, primeiro_nome, reais
from saturday.agent.coleta import hoje_operacao
from saturday.agent.context import AgentContext
from saturday.agent.state import AgentState
from saturday.bancos.granatech.cliente import ErroGranatech
from saturday.bancos.granatech.normalizacao import DetalheConsulta, Simulacao, Vinculo
from saturday.dados import consentimentos, recontatos
from saturday.dados.cota import CotaEsgotada
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.fontes.brasilapi import ErroBrasilAPI
from saturday.privacidade import mascarar_telefone
from saturday.settings import TZ_OPERACAO

logger = logging.getLogger(__name__)

ATIVAS = frozenset(
    {"abertura", "triagem", "empresa", "identificacao", "consentimento", "consultando"}
    | {"escolha_vinculo", "oferta", "recontato"}
    | {"dados_proposta", "aceite", "proposta", "formalizacao", "nova_conta"}
)
TRIAGEM = ("carteira", "tempo_casa", "contrato_especial", "granatech", "funcionarios")
# Resposta da triagem que reprova: (resposta, motivo do não elegível).
REPROVA = {
    "carteira": (False, "nao_elegivel_carteira"),
    "contrato_especial": (True, "nao_elegivel_contrato_especial"),
    "granatech": (True, "nao_elegivel_granatech"),
    "funcionarios": (False, "nao_elegivel_funcionarios"),
}
CONSENTIMENTO_CONSULTA = "consulta"
MAX_RECONTATOS_COTA = 3
HORA_RECONTATO = time(9, 0)


# ---------------------------------------------------------------- abertura e triagem


def _abertura(t: Turno) -> dict[str, Any]:
    t.clt.update(dados={}, novas_simulacoes=0)
    return t.perguntar("triagem", "carteira", texto("abertura"))


def _triagem(t: Turno) -> dict[str, Any]:
    passo = str(t.clt.get("passo"))
    if passo == "tempo_casa":
        meses = leitura.tempo_de_casa_meses(t.texto)
        if meses is None:
            return t.erro("repetir_tempo_casa")
        t.dados["meses_casa"] = meses
        if meses < regras.TEMPO_DE_CASA_MESES:
            return _recontato_tempo_casa(t, meses)
        return t.perguntar("triagem", "contrato_especial")

    resposta = leitura.sim_ou_nao(t.texto)
    if resposta is None:
        return t.erro("repetir_sim_nao")
    reprova, chave = REPROVA[passo]
    if resposta is reprova:
        return t.nao_elegivel(chave)
    if passo == "funcionarios":
        return t.perguntar("empresa", "cnpj")
    return t.perguntar("triagem", TRIAGEM[TRIAGEM.index(passo) + 1])


def _recontato_tempo_casa(t: Turno, meses: int) -> dict[str, Any]:
    """Menos de 12 meses de casa: pergunta se pode avisar quando completar (opt-in)."""

    quando = regras.data_recontato_tempo_casa(meses, t.hoje)
    t.clt.update(
        etapa="recontato",
        passo="optin",
        erros=0,
        motivo=recontatos.TEMPO_CASA,
        recontato_em=quando.isoformat(),
    )
    return t.responder(texto("recontato_tempo_casa", data=quando.strftime("%d/%m/%Y")))


def _as_nove(dia: date) -> datetime:
    return datetime.combine(dia, HORA_RECONTATO, tzinfo=ZoneInfo(TZ_OPERACAO))


# ---------------------------------------------------------------- empresa


def _empresa(t: Turno) -> dict[str, Any]:
    cnpj = leitura.cnpj(t.texto)
    if cnpj is None:
        return t.erro("cnpj_invalido")
    if t.contexto.brasilapi is None:
        return t.handoff("brasilapi_indisponivel")
    try:
        dados = t.contexto.brasilapi.buscar_empresa(cnpj, conversa_id=t.conversa_id)
    except ErroBrasilAPI:
        return t.handoff("brasilapi_indisponivel")
    if dados is None:
        return t.erro("cnpj_invalido")
    motivo = regras.empresa_reprovada(dados, t.hoje)
    if motivo is not None:
        logger.info("clt_empresa_reprovada motivo=%s", motivo)
        return t.nao_elegivel("nao_elegivel_empresa")
    t.dados["cnpj"] = cnpj
    return t.perguntar("identificacao", "cpf")


# ---------------------------------------------------------------- identificação


def _identificacao(t: Turno) -> dict[str, Any]:
    passo = str(t.clt.get("passo"))
    if passo == "cpf":
        cpf = leitura.cpf(t.texto)
        if cpf is None:
            return t.erro("cpf_invalido")
        t.dados["cpf"] = cpf
        return t.perguntar("identificacao", "nome")
    if passo == "nome":
        nome = leitura.nome_completo(t.texto)
        if nome is None:
            return t.erro("nome_invalido")
        t.dados["nome"] = nome
        return t.perguntar("identificacao", "nascimento")
    if passo == "nascimento":
        nascimento = leitura.data_nascimento(t.texto, t.hoje)
        if nascimento is None:
            return t.erro("nascimento_invalido")
        t.dados["nascimento"] = nascimento.isoformat()
        return t.perguntar("identificacao", "sexo")

    sexo = leitura.sexo(t.texto)
    if sexo is None:
        return t.erro("sexo_invalido")
    t.dados["sexo"] = sexo
    if not _prazos(t):
        return t.nao_elegivel("nao_elegivel_idade")
    return t.perguntar("consentimento", "email")


def _prazos(t: Turno) -> tuple[int, ...]:
    nascimento = date.fromisoformat(t.dados["nascimento"])
    return regras.prazos_permitidos(nascimento, t.dados["sexo"], t.hoje)


# ---------------------------------------------------------------- consentimento


def _consentimento(t: Turno) -> dict[str, Any]:
    passo = str(t.clt.get("passo"))
    if passo == "email":
        email = leitura.email(t.texto)
        if email is None:
            return t.erro("email_invalido")
        t.dados["email"] = email
        celular = leitura.celular(t.state.get("telefone") or "")
        if celular is None:
            return t.perguntar("consentimento", "celular")
        t.dados["celular"] = celular
        t.clt.update(passo="confirmar_celular", erros=0)
        return t.responder(texto("confirmar_celular", celular=mascarar_telefone(celular)))
    if passo == "confirmar_celular":
        resposta = leitura.sim_ou_nao(t.texto)
        if resposta is None:
            return t.erro("repetir_sim_nao")
        if resposta is False:
            t.dados.pop("celular", None)
            return t.perguntar("consentimento", "celular")
        return t.perguntar("consentimento", "sim")
    if passo == "celular":
        celular = leitura.celular(t.texto)
        if celular is None:
            return t.erro("celular_invalido")
        t.dados["celular"] = celular
        return t.perguntar("consentimento", "sim")

    # Passo `sim`: a última mensagem do agente foi o pedido de autorização.
    if leitura.consentiu(t.texto):
        return _autorizou(t)
    if leitura.NEGACAO.search(t.texto):
        return t.responder(texto("consentimento_recusado"))
    if leitura.eh_pergunta(t.texto):
        return t.faq()
    return t.responder(texto("repetir_consentimento"))


def _autorizou(t: Turno) -> dict[str, Any]:
    if t.contexto.fabrica is None or t.contexto.granatech is None:
        return t.handoff("granatech_indisponivel")
    consentimentos.gravar_prova(
        t.contexto.fabrica,
        conversa_id=t.conversa_id,
        tipo=CONSENTIMENTO_CONSULTA,
        texto_mostrado=texto("consentimento"),
        versao=versao(),
        resposta_literal=t.texto,
        wamid=t.state.get("message_id"),
        cpf=t.dados["cpf"],
    )
    return _consultar(t, recontato=None)


def _consultar(t: Turno, *, recontato: int | None) -> dict[str, Any]:
    """Abre (ou reaproveita) a consulta. Só depois de uma prova gravada."""

    granatech, fabrica = t.contexto.granatech, t.contexto.fabrica
    if granatech is None or fabrica is None:
        return t.handoff("granatech_indisponivel")
    with abrir_sessao(fabrica) as sessao:
        provado = consentimentos.existe_prova(
            sessao, conversa_id=t.conversa_id, tipo=CONSENTIMENTO_CONSULTA, cpf=t.dados["cpf"]
        )
    if not provado:
        # Regra 3: nenhuma consulta sem o SIM gravado. Não deve acontecer.
        logger.error("clt_consulta_sem_consentimento")
        return t.handoff("sem_consentimento")

    try:
        consulta = granatech.abrir_consulta(
            t.dados["cpf"], t.dados["nome"], t.dados["celular"], conversa_id=t.conversa_id
        )
    except CotaEsgotada:
        return _cota_esgotada(t, recontato)
    except ErroGranatech:
        return t.handoff("granatech_indisponivel")

    t.clt.update(etapa="consultando", passo=None, consulta=consulta.id_externo, erros=0)
    if not consulta.reaproveitada:
        try:
            granatech.assinar_termo(
                id_consulta=consulta.id_externo,
                cpf=t.dados["cpf"],
                email=t.dados["email"],
                nome=t.dados["nome"],
                telefone=t.dados["celular"],
                conversa_id=t.conversa_id,
            )
        except ErroGranatech:
            if not consulta.link_termo:
                return t.handoff("termo_falhou")
            return t.responder(texto("consultando"), texto("termo_link", link=consulta.link_termo))
    return _seguir_consulta(t, texto("consultando"))


def _cota_esgotada(t: Turno, recontato: int | None) -> dict[str, Any]:
    tentativas = 0 if recontato is None else recontato + 1
    if tentativas > MAX_RECONTATOS_COTA:
        return t.handoff("cota_esgotada")
    if t.contexto.fabrica is not None and t.conversa_id is not None:
        with abrir_sessao(t.contexto.fabrica) as sessao:
            recontatos.agendar(
                sessao,
                conversa_id=t.conversa_id,
                motivo=recontatos.COTA_ESGOTADA,
                quando=_as_nove(t.hoje + timedelta(days=1)),
                tentativas=tentativas,
            )
    t.clt.update(etapa="recontato", passo=None, motivo=recontatos.COTA_ESGOTADA)
    # No recontato o cliente já ouviu o aviso: só avisa de novo se for o primeiro.
    return t.responder(texto("cota_esgotada") if recontato is None else "")


def _seguir_consulta(t: Turno, *antes: str) -> dict[str, Any]:
    """Consulta pronta segue para o vínculo; senão, espera o evento."""

    status, _, detalhe = t.granatech.situacao(str(t.clt["consulta"]))
    if detalhe is None and status == "SUCCESS":
        try:
            detalhe = t.granatech.gravar_detalhe(str(t.clt["consulta"]))
        except ErroGranatech:
            detalhe = None
    if detalhe is not None:
        return _pos_consulta(t, detalhe)
    if status == "NO_MARGIN":
        return t.nao_elegivel("nao_elegivel_sem_margem")
    if status in ("USED", "UNEXPECTED_ERROR") or status.startswith(("FIDUCIARY", "WORKER")):
        return t.handoff("consulta_com_erro")
    return t.responder(*antes)


# ---------------------------------------------------------------- depois da consulta


def _consultando(t: Turno) -> dict[str, Any]:
    if leitura.eh_pergunta(t.texto):
        return t.faq()
    return t.responder(texto("aguardando_consulta"))


def _recontato(t: Turno) -> dict[str, Any]:
    if t.clt.get("motivo") == recontatos.TEMPO_CASA and t.clt.get("passo") == "optin":
        return _optin_tempo_casa(t)
    if t.clt.get("motivo") == recontatos.COTA_ESGOTADA and not leitura.eh_pergunta(t.texto):
        return t.responder(texto("aguardando_recontato"))
    return t.faq()


def _optin_tempo_casa(t: Turno) -> dict[str, Any]:
    resposta = leitura.sim_ou_nao(t.texto)
    if resposta is None:
        return t.erro("repetir_sim_nao")
    quando = date.fromisoformat(str(t.clt["recontato_em"]))
    t.clt.update(passo=None, erros=0)
    if resposta is False:
        proposta.gravar_marketing(t, "opt_out")
        return t.responder(texto("optin_recusado"))
    proposta.gravar_marketing(t, "opt_in")
    if t.contexto.fabrica is not None and t.conversa_id is not None:
        with abrir_sessao(t.contexto.fabrica) as sessao:
            recontatos.agendar(
                sessao,
                conversa_id=t.conversa_id,
                motivo=recontatos.TEMPO_CASA,
                quando=_as_nove(quando),
            )
    return t.responder(texto("optin_confirmado", data=quando.strftime("%d/%m/%Y")))


def _pos_consulta(t: Turno, detalhe: DetalheConsulta) -> dict[str, Any]:
    pessoa = detalhe.pessoa
    if pessoa is not None:
        # Vale o dado da Granatech quando diverge do informado.
        if pessoa.nascimento is not None:
            t.dados["nascimento"] = pessoa.nascimento.isoformat()
        sexo = (pessoa.sexo or "").strip()[:1].upper()
        if sexo in regras.LIMITE_IDADE:
            t.dados["sexo"] = sexo
    if not _prazos(t):
        return t.nao_elegivel("nao_elegivel_idade")
    vinculos = regras.vinculos_ofertaveis(detalhe)
    if not vinculos:
        return t.nao_elegivel("nao_elegivel_sem_margem")
    if len(vinculos) == 1:
        t.clt["id_margem"] = vinculos[0].id_margem
        return _simular(t, vinculos[0])
    t.clt.update(etapa="escolha_vinculo", passo="vinculo", erros=0)
    t.clt["vinculos"] = [v.id_margem for v in vinculos]
    opcoes = "\n".join(
        texto("opcao_vinculo", numero=i, empregador=v.nome_empregador, margem=reais(v.margem))
        for i, v in enumerate(vinculos, start=1)
    )
    return t.responder(texto("escolher_vinculo"), opcoes)


def _detalhe(t: Turno) -> DetalheConsulta:
    _, _, detalhe = t.granatech.situacao(str(t.clt["consulta"]))
    if detalhe is None:
        raise RuntimeError("consulta sem detalhe gravado")
    return detalhe


def _vinculo(t: Turno) -> Vinculo:
    alvo = t.clt["id_margem"]
    return next(v for v in _detalhe(t).vinculos if v.id_margem == alvo)


def _escolha_vinculo(t: Turno) -> dict[str, Any]:
    ids = list(t.clt.get("vinculos") or [])
    indice = leitura.numero_da_lista(t.texto, len(ids))
    if indice is None:
        return t.erro("vinculo_invalido")
    t.clt["id_margem"] = ids[indice]
    return _simular(t, _vinculo(t))


# ---------------------------------------------------------------- simulação e oferta


def _simular(
    t: Turno,
    vinculo: Vinculo,
    *,
    sem_seguro: bool = False,
    prazo: int | None = None,
    parcela: Decimal | None = None,
) -> dict[str, Any]:
    """Simula e apresenta a oferta. Repetição (``prazo``/``parcela``) mantém a anterior."""

    repeticao = "oferta" in t.clt
    escolha = regras.escolher_produto(
        vinculo, _prazos(t), sem_seguro=sem_seguro, prazo_desejado=prazo
    )
    if escolha is None:
        if repeticao:
            return t.responder(texto("sem_seguro_indisponivel"))
        return t.nao_elegivel("nao_elegivel_sem_oferta")
    produto, numero_parcelas = escolha
    nascimento = date.fromisoformat(t.dados["nascimento"])
    try:
        simulacao = t.granatech.simular_no_teto(
            id_produto=produto.id,
            id_margem=vinculo.id_margem,
            numero_parcelas=numero_parcelas,
            idade=regras.idade(nascimento, t.hoje),
            valor_parcela=parcela or vinculo.margem,
            seguro=produto.seguro,
            id_empresa_seguro=produto.id_empresa_seguro,
            id_produto_seguro=produto.id_produto_seguro,
        )
    except ErroGranatech:
        return t.handoff("granatech_indisponivel")
    if simulacao is None:
        if repeticao:
            return t.responder(texto("pedido_sem_oferta"))
        return t.nao_elegivel("nao_elegivel_sem_oferta")
    if simulacao.liberado > t.granatech.teto:
        # Regra 6: nunca apresentar acima do teto, nem por erro do cliente HTTP.
        return t.handoff("acima_do_teto")

    t.clt.update(etapa="oferta", passo=None, erros=0)
    t.clt["oferta"] = _guardar_oferta(produto.id, vinculo.id_margem, simulacao, sem_seguro)
    return t.responder(_texto_oferta(t, simulacao))


def _guardar_oferta(
    id_produto: str, id_margem: str, simulacao: Simulacao, sem_seguro: bool
) -> dict[str, Any]:
    """A simulação em texto puro: o checkpoint não precisa saber de ``Decimal``."""

    dados = {
        chave: (str(valor) if isinstance(valor, Decimal | date) else valor)
        for chave, valor in asdict(simulacao).items()
    }
    dados.update(id_produto=id_produto, id_margem=id_margem, pediu_sem_seguro=sem_seguro)
    return dados


def _texto_oferta(t: Turno, simulacao: Simulacao) -> str:
    valores: dict[str, object] = {
        "nome": primeiro_nome(t.dados.get("nome") or ""),
        "liberado": reais(simulacao.liberado),
        "n": simulacao.numero_parcelas,
        "parcela": reais(simulacao.valor_parcela),
        "taxa": reais(simulacao.taxa_mensal),
        "cet": reais(simulacao.cet_mensal),
    }
    # Regra 7: o texto segue o bloco que voltou, não o pedido.
    if simulacao.seguro_aplicado:
        oferta = texto("oferta", seguro=reais(simulacao.valor_seguro), **valores)
    else:
        oferta = texto("oferta_sem_seguro", **valores)
    if simulacao.limitado_ao_teto:
        aviso = texto("aviso_teto", teto=reais(t.granatech.teto))
        return f"{aviso}\n\n{oferta}"
    return oferta


def _oferta(t: Turno) -> dict[str, Any]:
    pedido = leitura.pedido_de_mudanca(t.texto)
    if pedido is None:
        if leitura.aceitou(t.texto):
            # Fase 5: o aceite vai para um especialista até a proposta existir.
            return proposta.iniciar(t)
        if leitura.eh_pergunta(t.texto):
            return t.faq()
        if leitura.sim_ou_nao(t.texto) is False:
            return t.responder(texto("oferta_recusada"))
        return t.responder(texto("pedido_nao_entendido"))

    vinculo = _vinculo(t)
    oferta = t.clt["oferta"]
    sem_seguro = pedido.sem_seguro or bool(oferta.get("pediu_sem_seguro"))
    if sem_seguro and not regras.prazos_disponiveis(vinculo, _prazos(t), True):
        return t.responder(texto("sem_seguro_indisponivel"))
    if pedido.parcelas is not None:
        disponiveis = regras.prazos_disponiveis(vinculo, _prazos(t), sem_seguro)
        if pedido.parcelas not in disponiveis:
            prazos = ", ".join(str(p) for p in disponiveis)
            return t.responder(texto("prazo_indisponivel", prazos=prazos))
    if pedido.valor_parcela is not None and pedido.valor_parcela > vinculo.margem:
        return t.responder(texto("parcela_acima_margem", margem=reais(vinculo.margem)))

    feitas = int(t.clt.get("novas_simulacoes") or 0)
    if feitas >= regras.MAX_NOVAS_SIMULACOES:
        return t.handoff("limite_simulacoes")
    t.clt["novas_simulacoes"] = feitas + 1
    return _simular(
        t,
        vinculo,
        sem_seguro=sem_seguro,
        prazo=pedido.parcelas or int(oferta["numero_parcelas"]),
        parcela=pedido.valor_parcela,
    )


# ---------------------------------------------------------------- eventos do sistema


def _evento(t: Turno, evento: str) -> dict[str, Any]:
    etapa = t.clt.get("etapa")
    nome, _, detalhe = evento.partition(":")
    if nome == "proposta":
        return proposta.evento(t, detalhe)
    if nome == "recontato_tempo_casa":
        return _recontato_tempo_casa_vencido(t)
    if nome == "recontato":
        if etapa != "recontato" or t.clt.get("motivo") != recontatos.COTA_ESGOTADA:
            return t.responder()
        return _consultar(t, recontato=int(detalhe or 0))
    if etapa != "consultando":
        # Evento atrasado ou repetido: a jornada já passou dessa etapa.
        return t.responder()
    if nome == "consulta_pronta":
        return _seguir_consulta(t)
    if nome == "consulta_sem_margem":
        return t.nao_elegivel("nao_elegivel_sem_margem")
    if nome == "consulta_erro":
        logger.info("clt_consulta_com_erro status=%s", detalhe)
        return t.handoff("consulta_com_erro")
    if nome == "termo_pendente":
        _, link, _ = t.granatech.situacao(str(t.clt["consulta"]))
        if not link:
            return t.handoff("termo_falhou")
        return t.responder(texto("termo_link", link=link))
    logger.warning("clt_evento_desconhecido evento=%s", nome)
    return t.responder()


def _recontato_tempo_casa_vencido(t: Turno) -> dict[str, Any]:
    """Data do recontato: modelo de marketing e a jornada recomeça pela triagem."""

    if proposta.marketing(t) != "opt_in" or t.clt.get("motivo") != recontatos.TEMPO_CASA:
        return t.responder()
    t.clt.clear()
    t.clt["etapa"] = "abertura"
    saida = t.responder()
    saida["modelo_envio"] = "recontato_tempo_casa"
    return saida


ETAPAS: dict[str, Callable[[Turno], dict[str, Any]]] = {
    "abertura": _abertura,
    "triagem": _triagem,
    "empresa": _empresa,
    "identificacao": _identificacao,
    "consentimento": _consentimento,
    "consultando": _consultando,
    "escolha_vinculo": _escolha_vinculo,
    "oferta": _oferta,
    "recontato": _recontato,
    "dados_proposta": proposta.dados_proposta,
    "aceite": proposta.aceite,
    "proposta": proposta.aguardando,
    "formalizacao": proposta.aguardando,
    "nova_conta": proposta.conta,
}


def clt(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    """Um passo da jornada CLT."""

    t = Turno(
        clt=copy.deepcopy(state.get("clt") or {}),
        state=state,
        contexto=runtime.context,
        texto=state.get("user_message") or "",
        hoje=hoje_operacao(),
    )
    evento = state.get("evento_sistema")
    if evento:
        return _evento(t, evento)
    if leitura.nao_quer_receber(t.texto):
        # Botão do modelo de marketing: vale em qualquer etapa.
        proposta.gravar_marketing(t, "opt_out")
        return t.responder(texto("optout"))
    etapa = str(t.clt.get("etapa") or "abertura")
    manipulador = ETAPAS.get(etapa)
    if manipulador is None:
        # `nao_elegivel`, `encerrada`, `pago`: a jornada acabou; só a FAQ responde.
        return t.faq()
    passo = str(t.clt.get("passo"))
    chave = PERGUNTAS.get(passo)
    if state.get("attachments") and chave and not variaveis(chaves()[chave]):
        return t.responder(texto("sem_documento", pergunta=texto(chave)))
    return manipulador(t)
