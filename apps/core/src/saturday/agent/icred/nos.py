"""Nós do iCred no ramo INSS (decisão 0027), fase 1.

`porta` roda depois do cálculo da portabilidade e, com o iCred ligado, pede o
SIM para consultar. `icred` conduz o resto: SIM, CPF, consulta, oferta do pacote
e aceite. A gravação da proposta é do atendente nesta fase.

Etapas em ``state["icred"]["etapa"]``: ``sim`` → ``cpf`` → ``consultando`` →
``oferta`` → ``fim``. "Seguir" é voltar ao caminho de antes do iCred: o cálculo
roda de novo e a conversa recebe a oferta de portabilidade ou o handoff dele.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from saturday.agent.clt import leitura
from saturday.agent.context import AgentContext
from saturday.agent.icred import regras, textos
from saturday.agent.state import AgentState
from saturday.bancos.icred.cliente import ErroIcred
from saturday.bancos.icred.normalizacao import ESTADOS_FINAIS
from saturday.dados import consentimentos
from saturday.dados.modelos import ConsultaIcred
from saturday.dados.sessao import sessao as abrir_sessao

logger = logging.getLogger(__name__)

# Etapas em que a próxima mensagem do cliente é do iCred.
ESPERANDO_CLIENTE = frozenset({"sim", "cpf", "oferta"})
EVENTO_RESULTADO = "icred:resultado"
EVENTO_PRAZO = "icred:prazo"
# Motivos de handoff do cálculo que ainda deixam consultar o iCred.
_MOTIVOS_COM_CONSULTA = frozenset({None, "sem_portabilidade"})


def _falar(dados: dict[str, Any], texto: str, chave: str) -> dict[str, Any]:
    return {
        "icred": dados,
        "status": "answered",
        "answer": texto,
        "chave_mensagem": chave,
        "needs_human": False,
        "handoff_reason": None,
        "messages": [AIMessage(content=texto)],
    }


def _seguir(dados: dict[str, Any]) -> dict[str, Any]:
    return {"icred": {**dados, "etapa": "fim"}, "icred_rota": "calculate_portability"}


def _handoff(dados: dict[str, Any], motivo: str, detalhe: dict[str, Any]) -> dict[str, Any]:
    return {
        "icred": {**dados, "etapa": "fim"},
        "needs_human": True,
        "handoff_reason": motivo,
        "handoff_detalhe": detalhe,
    }


def _conversa_id(state: AgentState) -> uuid.UUID | None:
    ref = state.get("conversa_ref")
    return uuid.UUID(ref) if ref else None


def _celular(telefone: str) -> str:
    """Celular com DDD, sem o 55 do WhatsApp."""

    digitos = "".join(c for c in telefone if c.isdigit())
    return digitos[2:] if len(digitos) > 11 and digitos.startswith("55") else digitos


def _valor_c6(state: AgentState) -> Decimal:
    resultado = state.get("portability_result") or {}
    if not any(c.get("elegivel") for c in resultado.get("contratos", [])):
        return Decimal(0)
    return Decimal(str(resultado.get("troco_total") or 0))


def porta(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    """Depois do cálculo: pede o SIM da consulta, uma vez por conversa."""

    if runtime.context.icred is None or state.get("handoff_reason") not in _MOTIVOS_COM_CONSULTA:
        return {}
    dados = dict(state.get("icred") or {})
    etapa = dados.get("etapa")
    # Extrato novo no meio da jornada do iCred: a pergunta aberta continua valendo,
    # senão o SIM seguinte responderia à oferta errada.
    if etapa in ("sim", "cpf"):
        return _falar({"etapa": "sim"}, textos.PEDIR_SIM, "icred:pedir_sim")
    if etapa == "consultando":
        return _falar(dados, textos.CONSULTANDO, "icred:consultando")
    if etapa == "oferta":
        return _falar(dados, textos.oferta(list(dados.get("contratos") or [])), "icred:oferta")
    if etapa or not state.get("telefone"):
        return {}
    return _falar({"etapa": "sim"}, textos.PEDIR_SIM, "icred:pedir_sim")


def _resposta(texto: str) -> bool | None:
    """SIM explícito (regra 3), NÃO, ou ``None`` quando não é nenhum dos dois."""

    if leitura.consentiu(texto):
        return True
    return False if leitura.NEGACAO.search(texto) else None


def icred(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, Any]:
    """Conduz a consulta ao iCred: SIM, CPF, resultado, oferta do pacote e aceite."""

    dados = dict(state.get("icred") or {})
    evento = state.get("evento_sistema")
    if evento:
        return _evento(state, runtime.context, dados, evento)
    etapa = dados.get("etapa")
    if etapa == "sim":
        return _sim(state, runtime.context, dados)
    if etapa == "cpf":
        return _cpf(state, runtime.context, dados)
    if etapa == "oferta":
        return _aceite(state, runtime.context, dados)
    return {"icred_rota": "classify_intent"}


def _sim(state: AgentState, contexto: AgentContext, dados: dict[str, Any]) -> dict[str, Any]:
    texto = state.get("user_message", "")
    resposta = _resposta(texto)
    if resposta is None:
        # Uma dúvida vai para o classificador; na segunda, o resultado do
        # extrato não espera mais pelo iCred.
        dados["tentativas"] = int(dados.get("tentativas") or 0) + 1
        if dados["tentativas"] >= 2:
            return _seguir(dados)
        return {"icred": dados, "icred_rota": "classify_intent"}
    if not resposta:
        return _seguir(dados)
    # A prova é gravada com o CPF, na etapa seguinte; aqui fica o SIM literal.
    dados.update(etapa="cpf", sim=texto, sim_wamid=state.get("message_id"), tentativas=0)
    # O CPF que a conversa já tem (pedido para o C6, decisão 0026) não é pedido de novo.
    cpf = leitura.cpf(str((state.get("cliente") or {}).get("cpf") or ""))
    if cpf is not None:
        return _consultar(state, contexto, dados, cpf)
    return _falar(dados, textos.PEDIR_CPF, "icred:pedir_cpf")


def _cpf(state: AgentState, contexto: AgentContext, dados: dict[str, Any]) -> dict[str, Any]:
    cpf = leitura.cpf(state.get("user_message", ""))
    if cpf is None:
        dados["tentativas"] = int(dados.get("tentativas") or 0) + 1
        if dados["tentativas"] >= 2:
            return _seguir(dados)
        return _falar(dados, textos.CPF_INVALIDO, "icred:cpf_invalido")
    return _consultar(state, contexto, dados, cpf)


def _consultar(
    state: AgentState, contexto: AgentContext, dados: dict[str, Any], cpf: str
) -> dict[str, Any]:
    cliente = contexto.icred
    telefone = state.get("telefone")
    if cliente is None or not telefone:
        return _seguir(dados)
    conversa_id = _conversa_id(state)
    consentimentos.gravar_prova(
        contexto.fabrica,
        conversa_id=conversa_id,
        tipo="icred_consulta",
        texto_mostrado=textos.PEDIR_SIM,
        versao=textos.VERSAO,
        resposta_literal=str(dados.pop("sim", "")),
        wamid=dados.pop("sim_wamid", None),
        cpf=cpf,
    )
    try:
        consulta = cliente.abrir_consulta(
            cpf=cpf, telefone=_celular(telefone), nome=None, conversa_id=conversa_id
        )
    except ErroIcred:
        logger.warning("icred_consulta_falhou")
        return _seguir(dados)
    dados.update(etapa="consultando", consulta=consulta)
    dados.pop("tentativas", None)
    return _falar(dados, textos.CONSULTANDO, "icred:consultando")


def _evento(
    state: AgentState, contexto: AgentContext, dados: dict[str, Any], evento: str
) -> dict[str, Any]:
    # Evento repetido, atrasado ou de uma consulta de que a conversa já desistiu.
    if dados.get("etapa") != "consultando":
        return {}
    if evento == EVENTO_PRAZO:
        return _seguir(dados)
    with abrir_sessao(contexto.fabrica) as sessao:
        linha = sessao.get(ConsultaIcred, dados.get("consulta"))
        if linha is None or linha.estado not in ESTADOS_FINAIS:
            return {}
        situacao, contratos = linha.situacao, linha.contratos
        valido_ate = linha.valido_ate

    decisao, motivo = regras.decidir(situacao, contratos, _valor_c6(state))
    if decisao == regras.HANDOFF and motivo:
        return _handoff(dados, motivo, {"icred_situacao": situacao})
    if decisao != regras.OFERTA or not contratos:
        return _seguir(dados)
    dados.update(
        etapa="oferta",
        contratos=contratos,
        valido_ate=valido_ate.isoformat() if valido_ate else None,
    )
    return _falar(dados, textos.oferta(contratos), "icred:oferta")


def _aceite(state: AgentState, contexto: AgentContext, dados: dict[str, Any]) -> dict[str, Any]:
    texto = state.get("user_message", "")
    resposta = _resposta(texto)
    if resposta is None:
        return {"icred_rota": "classify_intent"}
    if not resposta:
        return _seguir(dados)

    contratos = list(dados.get("contratos") or [])
    with abrir_sessao(contexto.fabrica) as sessao:
        linha = sessao.get(ConsultaIcred, dados.get("consulta"))
        cpf = linha.cpf if linha is not None else ""
        id_externo = linha.id_externo if linha is not None else None
    consentimentos.gravar_prova(
        contexto.fabrica,
        conversa_id=_conversa_id(state),
        tipo="icred_aceite",
        texto_mostrado=textos.oferta(contratos),
        versao=textos.VERSAO,
        resposta_literal=texto,
        wamid=state.get("message_id"),
        cpf=cpf,
    )
    valido_ate = dados.get("valido_ate")
    vencida = isinstance(valido_ate, str) and datetime.fromisoformat(valido_ate) < datetime.now(UTC)
    # Fase 1: o atendente grava pelo painel do motor. Consulta vencida pede nova
    # consulta antes de gravar.
    return _handoff(
        dados,
        "icred_aceite",
        {"icred_consulta": id_externo, "icred_contratos": contratos, "icred_vencida": vencida},
    )
