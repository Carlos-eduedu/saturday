"""Montagem do grafo do agente."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from saturday.agent.context import AgentContext
from saturday.agent.nodes import (
    calculate_portability,
    check_customer_data,
    classify_intent,
    collect_customer_data,
    decline_offer,
    generate_answer,
    handoff,
    present_offer,
    read_statement,
)
from saturday.agent.routing import (
    after_calculate,
    after_check,
    after_classify,
    after_collect,
    after_generate,
    after_read,
    route_start,
)
from saturday.agent.state import AgentState


def build_graph(checkpointer: Any = None) -> Any:
    """Monta e compila o grafo com o checkpointer recebido."""

    builder = StateGraph(AgentState, context_schema=AgentContext)

    builder.add_node("classify_intent", classify_intent)
    builder.add_node("generate_answer", generate_answer)
    builder.add_node("handoff", handoff)
    builder.add_node("decline_offer", decline_offer)
    builder.add_node("read_statement", read_statement)
    builder.add_node("check_customer_data", check_customer_data)
    builder.add_node("collect_customer_data", collect_customer_data)
    builder.add_node("calculate_portability", calculate_portability)
    builder.add_node("present_offer", present_offer)

    builder.add_conditional_edges(
        START,
        route_start,
        {
            "read_statement": "read_statement",
            "collect_customer_data": "collect_customer_data",
            "classify_intent": "classify_intent",
        },
    )
    builder.add_conditional_edges(
        "classify_intent",
        after_classify,
        {
            "handoff": "handoff",
            "decline_offer": "decline_offer",
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
    builder.add_edge("present_offer", END)
    builder.add_edge("decline_offer", END)
    builder.add_edge("handoff", END)

    return builder.compile(checkpointer=checkpointer)
