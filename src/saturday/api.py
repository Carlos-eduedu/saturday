"""API HTTP: entrada de mensagens, saída síncrona ou por webhook."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, FastAPI
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage

from saturday.agent.graph import graph
from saturday.agent.state import turno_inicial
from saturday.schemas import AgentReply, ChatRequest
from saturday.services import webhook
from saturday.settings import TZ_OPERACAO, get_settings

logger = logging.getLogger(__name__)

app = FastAPI(title="Saturday", version="0.1.0")


def _config(conversa_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": conversa_id}}


def _estado_atual(config: dict[str, Any]) -> dict[str, Any]:
    snapshot = graph.get_state(config)
    return snapshot.values or {}


def _evento(conversa_id: str, estado: dict[str, Any]) -> AgentReply:
    status = estado.get("status")
    if status not in ("answered", "handoff"):
        status = "answered"
    return AgentReply(
        conversation_id=conversa_id,
        answer=estado.get("answer") or "",
        status=cast(Literal["answered", "handoff"], status),
        intent=estado.get("intent"),
        publico=estado.get("publico"),
        handoff_reason=estado.get("handoff_reason"),
        portability_result=estado.get("portability_result"),
        timestamp=datetime.now(ZoneInfo(TZ_OPERACAO)),
    )


def _cliente_mesclado(estado: dict[str, Any], payload: ChatRequest) -> dict[str, Any]:
    cliente = dict(estado.get("cliente") or {})
    if payload.cliente is not None:
        for campo, valor in payload.cliente.model_dump(exclude_none=True).items():
            cliente[campo] = valor
    return cliente


def process_message(payload: ChatRequest) -> AgentReply | None:
    """Roda um turno. Devolve ``None`` se a conversa já está com um humano."""

    config = _config(payload.conversation_id)
    estado = _estado_atual(config)

    # Conversa em handoff fica congelada até um humano assumir.
    if estado.get("status") == "handoff":
        return None

    cliente = _cliente_mesclado(estado, payload)
    entrada = turno_inicial(
        user_message=payload.message,
        attachments=[a.model_dump(exclude_none=True) for a in payload.attachments],
    )
    if cliente:
        entrada["cliente"] = cliente
    if payload.message.strip():
        entrada["messages"] = [HumanMessage(content=payload.message)]

    final = graph.invoke(entrada, config)
    resultado = final.get("portability_result") or {}
    logger.info(
        "turno conversation_id=%s status=%s motivo=%s calculo_ok=%s",
        payload.conversation_id,
        final.get("status"),
        final.get("handoff_reason"),
        resultado.get("ok"),
    )
    return _evento(payload.conversation_id, final)


def _processar_e_enviar(payload: ChatRequest) -> None:
    try:
        resposta = process_message(payload)
    except Exception as exc:
        logger.error(
            "processamento_falhou conversation_id=%s erro=%s",
            payload.conversation_id,
            type(exc).__name__,
        )
        return
    if resposta is None:
        # Não envia nada: a conversa está com um atendente humano.
        return
    webhook.send(resposta.model_dump(mode="json"))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=None)
def chat(payload: ChatRequest, background_tasks: BackgroundTasks) -> JSONResponse | AgentReply:
    if get_settings().webhook_url:
        background_tasks.add_task(_processar_e_enviar, payload)
        return JSONResponse(
            status_code=202,
            content={
                "conversation_id": payload.conversation_id,
                "status": "accepted",
            },
        )

    resposta = process_message(payload)
    if resposta is None:
        # Sem webhook não há como "não responder": devolve o estado congelado.
        return _evento(
            payload.conversation_id,
            _estado_atual(_config(payload.conversation_id)),
        )
    return resposta
