"""Fábrica da aplicação FastAPI."""

from __future__ import annotations

from fastapi import FastAPI

from saturday.settings import Settings, get_settings
from saturday.web.api import chat, conversas, monitoring
from saturday.web.lifespan import criar_lifespan


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
    return app
