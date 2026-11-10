"""Montagem do serviço de agente.

Separado do `lifespan` de propósito: aqui dizemos *do que* a aplicação é feita,
lá cuidamos de *quando* cada recurso abre e fecha. As fases 2 e 4 acrescentam
canais e bancos nesta composição, sem mexer no ciclo de vida.
"""

from __future__ import annotations

from typing import Any

import httpx

from saturday.agent.context import AgentContext
from saturday.agent.graph import build_graph
from saturday.agent.service import AgentService
from saturday.services.anexos import AnexosClient
from saturday.services.jev import JevClient
from saturday.services.llm import LLMClient
from saturday.services.webhook import WebhookClient
from saturday.settings import Settings
from saturday.storage.base import Storage


def criar_contexto(http: httpx.Client, settings: Settings) -> AgentContext:
    """Clientes de IA e de leitura de anexo, compartilhando o mesmo `httpx`."""

    return AgentContext(
        jev=JevClient(http, settings),
        llm=LLMClient(http, settings),
        anexos=AnexosClient(http, settings),
    )


def criar_servico(
    *,
    http: httpx.Client,
    settings: Settings,
    checkpointer: Any,
    fabrica: Any,
    storage: Storage,
) -> AgentService:
    """Monta o serviço com o checkpointer e a fábrica de sessões já abertos."""

    return AgentService(
        graph=build_graph(checkpointer),
        context=criar_contexto(http, settings),
        webhook=WebhookClient(http, settings),
        settings=settings,
        checkpointer=checkpointer,
        fabrica=fabrica,
        storage=storage,
    )
