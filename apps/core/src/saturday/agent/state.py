"""Estado compartilhado entre os nós do grafo."""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import MessagesState


class AgentState(MessagesState, total=False):
    # Campos do turno corrente. O serviço que invoca o grafo zera todos eles.
    user_message: str
    attachments: list[dict[str, Any]]
    intent: str | None
    intent_confidence: float | None
    needs_human: bool
    status: Literal["in_progress", "answered", "handoff"]
    answer: str | None
    handoff_reason: str | None
    resposta_oferta: str | None

    # Campos persistentes da conversa.
    publico: str | None
    cliente: dict[str, Any]
    hiscon: dict[str, Any] | None
    hiscon_recebido_em: str | None
    aguardando: Literal["data_nascimento", "uf"] | None
    tentativas_coleta: int
    tentativas_extrato: int
    portability_result: dict[str, Any] | None
    oferta_pendente: bool
    handoff_em: str | None
    # Sem reducer de propósito: a lista é substituída a cada gravação.
    message_ids_recentes: list[str]


CAMPOS_DO_TURNO = (
    "intent",
    "intent_confidence",
    "needs_human",
    "answer",
    "handoff_reason",
    "resposta_oferta",
)


def turno_inicial(
    *,
    user_message: str,
    attachments: list[dict[str, Any]],
    cliente: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Campos que precisam ser reiniciados a cada turno."""

    estado: dict[str, Any] = {
        "user_message": user_message,
        "attachments": attachments,
        "intent": None,
        "intent_confidence": None,
        "needs_human": False,
        "status": "in_progress",
        "answer": None,
        "handoff_reason": None,
        "resposta_oferta": None,
    }
    if cliente:
        estado["cliente"] = cliente
    return estado
