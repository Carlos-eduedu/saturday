"""Rota de conversa."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse

from saturday.agent.service import AgentService
from saturday.schemas import AgentReply, ChatRequest
from saturday.web.dependencies import get_agent_service

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=None)
def chat(
    payload: ChatRequest,
    background_tasks: BackgroundTasks,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> JSONResponse | AgentReply:
    if service.webhook.configurado:
        background_tasks.add_task(service.processar_e_enviar, payload)
        return JSONResponse(
            status_code=202,
            content={
                "conversation_id": payload.conversation_id,
                "status": "accepted",
            },
        )

    resposta = service.process_message(payload)
    if resposta is None:
        # Sem webhook não há como "não responder": devolve o estado congelado.
        return service.evento_atual(payload.conversation_id)
    return resposta
