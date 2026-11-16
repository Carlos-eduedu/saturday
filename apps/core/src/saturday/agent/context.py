"""Contexto injetado nos nós do grafo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from saturday.services.anexos import AnexosClient
from saturday.services.jev import JevClient
from saturday.services.llm import LLMClient

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from saturday.bancos.granatech.cliente import ClienteGranatech
    from saturday.conhecimento import Conhecimento
    from saturday.fontes.brasilapi import BrasilAPI


@dataclass(frozen=True)
class AgentContext:
    """Serviços compartilhados por uma execução do grafo.

    ``granatech`` e ``brasilapi`` só existem com ``SATURDAY_GRANATECH_ATIVO``:
    sem eles o ramo CLT fica desligado e o comportamento é o de antes.
    """

    jev: JevClient
    llm: LLMClient
    anexos: AnexosClient
    fabrica: sessionmaker[Session]
    granatech: ClienteGranatech | None = None
    # Cliente do simulador para conversa de membro testador (decisão 0020);
    # só com `SATURDAY_GRANATECH_SIMULADOR_URL` (dev e homolog).
    granatech_teste: ClienteGranatech | None = None
    brasilapi: BrasilAPI | None = None
    # `SATURDAY_C6_ATIVO`: o ramo INSS pede o SIM para simular no C6 (decisão 0026).
    c6_ativo: bool = False
    # Domínio dos links curtos da biometria (`SATURDAY_DOMINIO_PUBLICO`).
    dominio_publico: str = ""
    # Base de conhecimento (RAG) do nó de respostas; sem ela, só a FAQ fixa.
    conhecimento: Conhecimento | None = None
