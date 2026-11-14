"""Montagem do grafo do agente."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from saturday.agent.clt.nos import clt
from saturday.agent.context import AgentContext
from saturday.agent.nodes import (
    boas_vindas,
    calculate_portability,
    check_customer_data,
    classify_intent,
    collect_customer_data,
    decline_offer,
    generate_answer,
    handoff,
    pedir_texto,
    present_offer,
    read_statement,
)
from saturday.agent.routing import (
    after_calculate,
    after_check,
    after_classify,
    after_clt,
    after_collect,
    after_generate,
    after_read,
    route_start,
)
from saturday.agent.state import AgentState

# Nós do grafo, na ordem em que entram. A aba Agente do painel lê daqui a
# descrição de cada nó (docstring).
NOS: dict[str, Any] = {
    "pedir_texto": pedir_texto,
    "boas_vindas": boas_vindas,
    "classify_intent": classify_intent,
    "generate_answer": generate_answer,
    "handoff": handoff,
    "decline_offer": decline_offer,
    "read_statement": read_statement,
    "check_customer_data": check_customer_data,
    "collect_customer_data": collect_customer_data,
    "calculate_portability": calculate_portability,
    "present_offer": present_offer,
    "clt": clt,
}


def build_graph(checkpointer: Any = None) -> Any:
    """Monta e compila o grafo com o checkpointer recebido."""

    builder = StateGraph(AgentState, context_schema=AgentContext)

    for nome, no in NOS.items():
        builder.add_node(nome, no)

    builder.add_conditional_edges(
        START,
        route_start,
        {
            "read_statement": "read_statement",
            "pedir_texto": "pedir_texto",
            "collect_customer_data": "collect_customer_data",
            "classify_intent": "classify_intent",
            "clt": "clt",
        },
    )
    builder.add_conditional_edges(
        "classify_intent",
        after_classify,
        {
            "handoff": "handoff",
            "decline_offer": "decline_offer",
            "collect_customer_data": "collect_customer_data",
            "generate_answer": "generate_answer",
            "clt": "clt",
            "boas_vindas": "boas_vindas",
        },
    )
    builder.add_conditional_edges(
        "clt",
        after_clt,
        {
            END: END,
            "handoff": "handoff",
            "generate_answer": "generate_answer",
        },
    )
    builder.add_conditional_edges(
        "generate_answer",
        after_generate,
        {
            END: END,
            "handoff": "handoff",
        },
    )
    builder.add_conditional_edges(
        "read_statement",
        after_read,
        {
            "handoff": "handoff",
            "check_customer_data": "check_customer_data",
            END: END,
        },
    )
    builder.add_conditional_edges(
        "check_customer_data",
        after_check,
        {
            "calculate_portability": "calculate_portability",
            END: END,
        },
    )
    builder.add_conditional_edges(
        "collect_customer_data",
        after_collect,
        {
            "handoff": "handoff",
            "check_customer_data": "check_customer_data",
            END: END,
        },
    )
    builder.add_conditional_edges(
        "calculate_portability",
        after_calculate,
        {
            "present_offer": "present_offer",
            "handoff": "handoff",
        },
    )
    builder.add_edge("pedir_texto", END)
    builder.add_edge("boas_vindas", END)
    builder.add_edge("present_offer", END)
    builder.add_edge("decline_offer", END)
    builder.add_edge("handoff", END)

    return builder.compile(checkpointer=checkpointer)
