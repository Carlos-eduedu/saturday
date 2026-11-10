"""Contexto injetado nos nós do grafo."""

from __future__ import annotations

from dataclasses import dataclass

from saturday.services.anexos import AnexosClient
from saturday.services.jev import JevClient
from saturday.services.llm import LLMClient


@dataclass(frozen=True)
class AgentContext:
    """Serviços compartilhados por uma execução do grafo."""

    jev: JevClient
    llm: LLMClient
    anexos: AnexosClient
