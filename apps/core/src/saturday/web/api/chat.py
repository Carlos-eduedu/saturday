"""Rota de conversa."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import JSONResponse

from saturday.agent.service import AgentService
from saturday.schemas import AcceptedReply, AgentReply, ChatRequest
from saturday.web.dependencies import get_agent_service, verificar_api_key

router = APIRouter(tags=["chat"], dependencies=[Depends(verificar_api_key)])


@router.post(
    "/chat",
    response_model=AgentReply,
    responses={
        202: {"model": AcceptedReply},
        401: {"description": "não autorizado"},
    },
)
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

    return service.process_message(payload)
