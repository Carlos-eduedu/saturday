"""Contrato do storage de anexos."""

from __future__ import annotations

from typing import Protocol

from saturday.settings import Settings
from saturday.storage.memoria import MemoriaStorage
from saturday.storage.s3 import S3Storage


class Storage(Protocol):
    """Guarda bytes de anexo fora do estado do grafo."""

    def salvar(self, dados: bytes, *, mime_type: str) -> str:
        """Guarda e devolve a chave. A chave é o que entra no estado."""
        ...

    def ler(self, chave: str) -> bytes: ...

    def apagar(self, chave: str) -> None: ...


def criar_storage(settings: Settings) -> Storage:
    """S3 quando há bucket; memória em `pytest`."""

    if settings.environment == "pytest" or not settings.s3_bucket:
        return MemoriaStorage()
    return S3Storage(settings)
