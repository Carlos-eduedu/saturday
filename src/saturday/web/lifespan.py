"""Startup e shutdown dos recursos compartilhados da aplicação."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
from fastapi import FastAPI
from langgraph.checkpoint.memory import InMemorySaver

from saturday.agent.context import AgentContext
from saturday.agent.graph import build_graph
from saturday.agent.service import AgentService
from saturday.log import configurar_logging
from saturday.services.anexos import AnexosClient
from saturday.services.jev import JevClient
from saturday.services.llm import LLMClient
from saturday.services.webhook import WebhookClient
from saturday.settings import Settings


def criar_lifespan(
    settings: Settings,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configurar_logging(settings.log_level)
        settings.validar_para_subir()
        app.state.settings = settings
        settings.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

        http = httpx.Client(
            timeout=httpx.Timeout(30.0),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
            ),
        )
        context = AgentContext(
            jev=JevClient(http, settings),
            llm=LLMClient(http, settings),
            anexos=AnexosClient(http, settings),
        )
        checkpointer = InMemorySaver()
        graph = build_graph(checkpointer)
        service = AgentService(
            graph=graph,
            context=context,
            webhook=WebhookClient(http, settings),
            settings=settings,
        )
        app.state.agent_service = service
        app.state.http = http
        app.state.checkpointer = checkpointer

        try:
            yield
        finally:
            http.close()

    return lifespan
