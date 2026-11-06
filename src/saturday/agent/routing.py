"""Funções das arestas condicionais do grafo."""

from __future__ import annotations

from langgraph.graph import END

from saturday.agent.state import AgentState
from saturday.settings import JEV_INTENT_THRESHOLD


def route_start(state: AgentState) -> str:
    if state.get("attachments"):
        return "read_statement"
    if state.get("aguardando"):
        return "collect_customer_data"
    return "classify_intent"


def after_classify(state: AgentState) -> str:
    if (
        state.get("intent") == "humano"
        and (state.get("intent_confidence") or 0.0) >= JEV_INTENT_THRESHOLD
    ):
        return "handoff"
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
