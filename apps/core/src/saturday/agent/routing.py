"""Funções das arestas condicionais do grafo."""

from __future__ import annotations

from langgraph.graph import END

from saturday.agent.clt.nos import ATIVAS
from saturday.agent.coleta import hoje_operacao, texto_valido_para
from saturday.agent.state import AgentState


def _etapa_clt(state: AgentState) -> str | None:
    etapa = (state.get("clt") or {}).get("etapa")
    return str(etapa) if etapa else None


def route_start(state: AgentState) -> str:
    if state.get("evento_sistema"):
        return "clt"
    if state.get("attachments") and _etapa_clt(state) in ATIVAS:
        # No CLT não há extrato para ler: a etapa responde com a pergunta atual.
        return "clt"
    if state.get("attachments"):
        return "read_statement"
    texto = state.get("user_message", "")
    if not texto.strip():
        return "pedir_texto"
    aguardando = state.get("aguardando")
    if aguardando and texto_valido_para(aguardando, texto, hoje_operacao()):
        return "collect_customer_data"
    return "classify_intent"


def after_classify(state: AgentState) -> str:
    if state.get("handoff_reason") == "pediu_humano":
        return "handoff"
    if _etapa_clt(state):
        return "clt"
    if state.get("aguardando"):
        return "collect_customer_data"
    if state.get("oferta_pendente"):
        if state.get("resposta_oferta") == "aceita":
            return "handoff"
        if state.get("resposta_oferta") == "recusa":
            return "decline_offer"
    return "generate_answer"


def after_generate(state: AgentState) -> str:
    if state.get("status") == "answered":
        return END
    return "handoff"


def after_read(state: AgentState) -> str:
    if state.get("handoff_reason"):
        return "handoff"
    if state.get("status") == "answered":
        return END
    return "check_customer_data"


def after_check(state: AgentState) -> str:
    if state.get("status") == "answered":
        return END
    return "calculate_portability"


def after_collect(state: AgentState) -> str:
    if state.get("handoff_reason"):
        return "handoff"
    if state.get("status") == "answered":
        return END
    return "check_customer_data"


def after_calculate(state: AgentState) -> str:
    if state.get("handoff_reason"):
        return "handoff"
    resultado = state.get("portability_result") or {}
    if any(c.get("elegivel") for c in resultado.get("contratos", [])):
        return "present_offer"
    return "handoff"


def after_clt(state: AgentState) -> str:
    if state.get("handoff_reason"):
        return "handoff"
    if state.get("clt_faq"):
        return "generate_answer"
    return END
