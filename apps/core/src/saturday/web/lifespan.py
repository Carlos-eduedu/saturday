"""Startup e shutdown dos recursos compartilhados da aplicação."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from saturday.dados.sessao import criar_engine, criar_factory
from saturday.log import configurar_logging
from saturday.settings import Settings
from saturday.storage.base import criar_storage
from saturday.web.composicao import criar_servico

logger = logging.getLogger(__name__)


def _checkpointer_de_teste() -> Any:
    """``pytest`` não sobe Postgres: o checkpointer fica na memória."""

    return InMemorySaver()


def criar_lifespan(
    settings: Settings,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configurar_logging(settings.log_level)
        settings.validar_para_subir()
        app.state.settings = settings
        if not settings.api_key.get_secret_value() and settings.environment in ("dev", "pytest"):
            logger.warning("api_key_desligada ambiente=%s", settings.environment)

        de_teste = settings.environment == "pytest"
        engine = None if de_teste else criar_engine(settings)
        fabrica = None if engine is None else criar_factory(engine)
        pool: ConnectionPool[Connection[dict[str, Any]]] | None = None
        if de_teste:
            checkpointer = _checkpointer_de_teste()
        else:
            # O pool é o que permite vários turnos ao mesmo tempo: o
            # PostgresSaver usa uma conexão por operação. `dict_row` é exigido
            # pelo formato de linha que o checkpointer lê.
            pool = ConnectionPool(
                conninfo=settings.database_url.get_secret_value(),
                max_size=10,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                },
                open=True,
            )
            checkpointer = PostgresSaver(pool)
            checkpointer.setup()

        http = httpx.Client(
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
            ),
        )
        service = criar_servico(
            http=http,
            settings=settings,
            checkpointer=checkpointer,
            fabrica=fabrica,
            storage=criar_storage(settings),
        )
        app.state.agent_service = service
        app.state.http = http
        app.state.checkpointer = checkpointer

        try:
            yield
        finally:
            http.close()
            if pool is not None:
                pool.close()
            if engine is not None:
                engine.dispose()

    return lifespan
