"""Dependências compartilhadas pelas rotas."""

from __future__ import annotations

import secrets
from typing import Annotated, cast

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from saturday.agent.service import AgentService
from saturday.settings import Settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_agent_service(request: Request) -> AgentService:
    """Devolve o serviço criado no lifespan (ou substituído em testes)."""

    return cast(AgentService, request.app.state.agent_service)


def verificar_api_key(
    request: Request,
    recebida: Annotated[str | None, Security(api_key_header)] = None,
) -> None:
    """Valida o header ``X-API-Key`` quando a chave está configurada."""

    settings = cast(Settings, request.app.state.settings)
    esperada = settings.api_key.get_secret_value()
    if not esperada:
        if settings.environment == "prod":
            raise HTTPException(status_code=401, detail="não autorizado")
        return

    if recebida is None or not secrets.compare_digest(recebida.encode(), esperada.encode()):
        raise HTTPException(status_code=401, detail="não autorizado")
