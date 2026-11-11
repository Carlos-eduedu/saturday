"""Montagem das dependências da aplicação.

Separado do `lifespan` de propósito: aqui dizemos *do que* a aplicação é feita,
lá cuidamos de *quando* cada recurso abre e fecha. A API e o worker montam as
mesmas peças por este arquivo.
"""

from __future__ import annotations

from typing import Any

import httpx
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from saturday.agent.context import AgentContext
from saturday.agent.graph import build_graph
from saturday.agent.service import AgentService
from saturday.canais.whatsapp.cliente import WhatsAppClient
from saturday.canais.whatsapp.entrada import EntradaWhatsApp
from saturday.canais.whatsapp.saida import SaidaWhatsApp
from saturday.services.anexos import AnexosClient
from saturday.services.jev import JevClient
from saturday.services.llm import LLMClient
from saturday.services.transcricao import Transcritor
from saturday.services.webhook import WebhookClient
from saturday.settings import Settings
from saturday.storage.base import Storage


def criar_contexto(
    http: httpx.Client,
    settings: Settings,
    storage: Storage | None = None,
) -> AgentContext:
    """Clientes de IA e de leitura de anexo, compartilhando o mesmo `httpx`."""

    return AgentContext(
        jev=JevClient(http, settings),
        llm=LLMClient(http, settings),
        anexos=AnexosClient(http, settings, storage),
    )


def criar_checkpointer(
    settings: Settings,
) -> tuple[Any, ConnectionPool[Connection[dict[str, Any]]] | None]:
    """`PostgresSaver` fora de `pytest`; memória dentro.

    O pool é o que permite vários turnos ao mesmo tempo: o checkpointer usa uma
    conexão por operação, e `dict_row` é o formato de linha que ele lê.
    """

    if settings.environment == "pytest":
        return InMemorySaver(), None

    pool: ConnectionPool[Connection[dict[str, Any]]] = ConnectionPool(
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
    return checkpointer, pool


def criar_canal_whatsapp(
    http: httpx.Client,
    settings: Settings,
    fabrica: Any,
    storage: Storage,
) -> tuple[EntradaWhatsApp, SaidaWhatsApp]:
    """Entrada (evento → turno) e saída (outbox → envio) do WhatsApp."""

    cliente = WhatsAppClient(http, settings)
    return (
        EntradaWhatsApp(cliente, storage, Transcritor(http, settings)),
        SaidaWhatsApp(cliente, fabrica, settings),
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
        context=criar_contexto(http, settings, storage),
        webhook=WebhookClient(http, settings),
        settings=settings,
        checkpointer=checkpointer,
        fabrica=fabrica,
        storage=storage,
    )
