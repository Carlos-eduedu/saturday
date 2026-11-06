"""Dependências compartilhadas pelas rotas."""

from __future__ import annotations

from typing import cast

from fastapi import Request

from saturday.agent.service import AgentService


def get_agent_service(request: Request) -> AgentService:
    """Devolve o serviço criado no lifespan (ou substituído em testes)."""

    return cast(AgentService, request.app.state.agent_service)
