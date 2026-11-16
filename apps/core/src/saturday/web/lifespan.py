"""Startup e shutdown dos recursos compartilhados da aplicação."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
from fastapi import FastAPI

from saturday.dados.sessao import criar_engine, criar_factory
from saturday.log import configurar_logging
from saturday.settings import Settings
from saturday.storage.base import criar_storage
from saturday.web.composicao import criar_checkpointer, criar_servico
from saturday.web.eventos import Difusor

logger = logging.getLogger(__name__)


def criar_lifespan(
    settings: Settings,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configurar_logging(settings.log_level)
        settings.validar_para_subir()
        app.state.settings = settings
        if not settings.api_key.get_secret_value() and settings.environment in ("dev", "pytest"):
            logger.warning("autenticacao_desligada ambiente=%s", settings.environment)

        # O banco é obrigatório em todo ambiente (docs/decisoes/0022); em
        # `pytest` só o checkpointer e o storage ficam em memória.
        engine = criar_engine(settings)
        fabrica = criar_factory(engine)
        checkpointer, pool = criar_checkpointer(settings)

        http = httpx.Client(
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
            ),
        )
        storage = criar_storage(settings)
        service = criar_servico(
            http=http,
            settings=settings,
            checkpointer=checkpointer,
            fabrica=fabrica,
            storage=storage,
        )
        app.state.agent_service = service
        app.state.http = http
        app.state.checkpointer = checkpointer
        # O webhook precisa da fábrica para enfileirar eventos.
        app.state.fabrica = fabrica
        app.state.storage = storage
        difusor = Difusor(settings.database_url.get_secret_value())
        difusor.iniciar()
        app.state.difusor = difusor

        try:
            yield
        finally:
            await difusor.parar()
            http.close()
            if pool is not None:
                pool.close()
            engine.dispose()

    return lifespan
