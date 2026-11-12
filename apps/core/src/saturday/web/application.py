"""Fábrica da aplicação FastAPI."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from saturday.settings import Settings, get_settings
from saturday.web.api import (
    admin,
    canais,
    chat,
    conversas,
    evolution,
    granatech,
    ia,
    links,
    monitoring,
    webhooks,
    whatsapp,
)
from saturday.web.lifespan import criar_lifespan
from saturday.web.limites import LimiteDeCorpo

logger = logging.getLogger(__name__)


def get_app(settings: Settings | None = None) -> FastAPI:
    """Monta a aplicação. Usada como factory pelo uvicorn."""

    settings = settings or get_settings()
    producao = settings.environment == "prod"
    app = FastAPI(
        title="Saturday",
        version="0.1.0",
        lifespan=criar_lifespan(settings),
        docs_url=None if producao else "/docs",
        redoc_url=None if producao else "/redoc",
        openapi_url=None if producao else "/openapi.json",
    )
    app.state.settings = settings
    # Recusa corpo acima de 20 MB antes de qualquer leitura de schema.
    app.add_middleware(LimiteDeCorpo)
    app.include_router(monitoring.router)
    app.include_router(chat.router)
    app.include_router(conversas.router)
    app.include_router(whatsapp.router)
    app.include_router(granatech.router)
    app.include_router(evolution.router)
    app.include_router(links.router)
    app.include_router(admin.router)
    app.include_router(canais.router)
    app.include_router(ia.router)
    webhooks.documentar_webhook(app)

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
