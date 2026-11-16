"""Montagem das dependências da aplicação.

Separado do `lifespan` de propósito: aqui dizemos *do que* a aplicação é feita,
lá cuidamos de *quando* cada recurso abre e fecha. A API e o worker montam as
mesmas peças por este arquivo.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.context import AgentContext
from saturday.agent.graph import build_graph
from saturday.agent.service import AgentService
from saturday.agente_config import Modelos
from saturday.bancos.granatech.cliente import ClienteGranatech
from saturday.canais.evolution.cliente import EvolutionClient
from saturday.canais.evolution.saida import SaidaEvolution
from saturday.canais.whatsapp.cliente import WhatsAppClient
from saturday.canais.whatsapp.entrada import EntradaWhatsApp
from saturday.canais.whatsapp.saida import SaidaWhatsApp
from saturday.conhecimento import Conhecimento
from saturday.fontes.brasilapi import BrasilAPI
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
    storage: Storage | None,
    fabrica: sessionmaker[Session],
) -> AgentContext:
    """Clientes de IA, de anexo e, com a Granatech ligada, os do ramo CLT.

    Todos compartilham o mesmo `httpx`. API e worker montam o contexto por aqui,
    porque os dois rodam turnos (o `POST /chat` sem webhook roda na API).
    """

    granatech = criar_cliente_granatech(http, settings, fabrica)
    modelos = Modelos(settings, fabrica)
    return AgentContext(
        jev=JevClient(http, settings, modelos),
        llm=LLMClient(http, settings, modelos),
        anexos=AnexosClient(http, settings, storage),
        granatech=granatech,
        granatech_teste=criar_cliente_granatech_teste(http, settings, fabrica),
        brasilapi=BrasilAPI(http, fabrica) if granatech is not None else None,
        fabrica=fabrica,
        c6_ativo=settings.c6_ativo,
        dominio_publico=settings.dominio_publico,
        conhecimento=Conhecimento(http, settings, fabrica, modelos),
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
        EntradaWhatsApp(cliente, storage, Transcritor(http, settings, Modelos(settings, fabrica))),
        SaidaWhatsApp(cliente, fabrica, settings, storage=storage),
    )


@dataclass(frozen=True)
class CanalEvolution:
    """Entrada, saída e o cliente (gestão das instâncias) da Evolution."""

    entrada: EntradaWhatsApp
    saida: SaidaEvolution
    cliente: EvolutionClient


def criar_canal_evolution(
    http: httpx.Client,
    settings: Settings,
    fabrica: Any,
    storage: Storage,
) -> CanalEvolution | None:
    """Canal da Evolution, ou ``None`` com ``SATURDAY_EVOLUTION_ATIVO`` desligado."""

    if not settings.evolution_ativo:
        return None
    cliente = EvolutionClient(http, settings)
    return CanalEvolution(
        entrada=EntradaWhatsApp(
            cliente,
            storage,
            Transcritor(http, settings, Modelos(settings, fabrica)),
            canal="evolution",
        ),
        saida=SaidaEvolution(cliente, fabrica, storage=storage),
        cliente=cliente,
    )


def criar_cliente_granatech(
    http: httpx.Client,
    settings: Settings,
    fabrica: sessionmaker[Session],
) -> ClienteGranatech | None:
    """Cliente da Granatech, ou ``None`` com ``SATURDAY_GRANATECH_ATIVO`` desligado."""

    if not settings.granatech_ativo:
        return None
    return ClienteGranatech(http, settings, fabrica)


def criar_cliente_granatech_teste(
    http: httpx.Client,
    settings: Settings,
    fabrica: sessionmaker[Session],
) -> ClienteGranatech | None:
    """Cliente do simulador para membro testador, ou ``None`` sem o simulador."""

    if not settings.granatech_ativo or not settings.granatech_simulador_url:
        return None
    simulador = settings.model_copy(
        update={
            "granatech_base_url": settings.granatech_simulador_url,
            "granatech_chave_api": settings.granatech_simulador_chave,
        }
    )
    return ClienteGranatech(http, simulador, fabrica, teste=True)


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
        context=criar_contexto(http, settings, storage, fabrica),
        webhook=WebhookClient(http, settings),
        settings=settings,
        checkpointer=checkpointer,
        fabrica=fabrica,
        storage=storage,
    )
