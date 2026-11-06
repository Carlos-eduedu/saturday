"""Rotas de gerenciamento das conversas."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from saturday.agent.service import AgentService
from saturday.schemas import ConversationState, ReleaseReply
from saturday.web.dependencies import get_agent_service, verificar_api_key

router = APIRouter(
    prefix="/conversations",
    tags=["conversas"],
    dependencies=[Depends(verificar_api_key)],
)


def _nao_encontrada() -> HTTPException:
    return HTTPException(status_code=404, detail="conversa não encontrada")


@router.get("/{conversation_id}", response_model=ConversationState)
def get_conversation(
    conversation_id: str,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> ConversationState:
    estado = service.estado_atual(service.config(conversation_id))
    if not estado:
        raise _nao_encontrada()
    return ConversationState(
        conversation_id=conversation_id,
        status=estado.get("status") or "in_progress",
        handoff_reason=estado.get("handoff_reason"),
        handoff_em=estado.get("handoff_em"),
        oferta_pendente=bool(estado.get("oferta_pendente")),
        aguardando=estado.get("aguardando"),
    )


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: str,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> Response:
    if service.checkpointer is None:
        raise HTTPException(status_code=500, detail="checkpointer indisponível")
    service.checkpointer.delete_thread(conversation_id)
    return Response(status_code=204)


@router.post("/{conversation_id}/release", response_model=ReleaseReply)
def release_conversation(
    conversation_id: str,
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> ReleaseReply:
    resultado = service.liberar(conversation_id)
    if resultado is None:
        raise _nao_encontrada()
    return ReleaseReply(
        conversation_id=conversation_id,
        status="in_progress",
    )
