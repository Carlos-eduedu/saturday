"""Fábrica da aplicação FastAPI."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from saturday.settings import Settings, get_settings
from saturday.web.api import chat, conversas, monitoring
from saturday.web.lifespan import criar_lifespan

logger = logging.getLogger(__name__)


def get_app(settings: Settings | None = None) -> FastAPI:
    """Monta a aplicação. Usada como factory pelo uvicorn."""

    settings = settings or get_settings()
    app = FastAPI(
        title="Saturday",
        version="0.1.0",
        lifespan=criar_lifespan(settings),
    )
    app.state.settings = settings
    app.include_router(monitoring.router)
    app.include_router(chat.router)
    app.include_router(conversas.router)

    @app.exception_handler(Exception)
    async def erro_nao_tratado(request: Request, exc: Exception) -> JSONResponse:
        # Sem stack trace e sem dados pessoais na resposta ao cliente.
        logger.error(
            "erro_nao_tratado rota=%s erro=%s",
            request.url.path,
            type(exc).__name__,
        )
        return JSONResponse(status_code=500, content={"detail": "erro interno"})

    return app
