"""Contrato do storage de anexos."""

from __future__ import annotations

from typing import Protocol, cast

from saturday.settings import Settings
from saturday.storage.memoria import MemoriaStorage
from saturday.storage.s3 import S3Storage


class Storage(Protocol):
    """Guarda bytes de anexo fora do estado do grafo."""

    def salvar(self, dados: bytes, *, mime_type: str, chave: str | None = None) -> str:
        """Guarda e devolve a chave. A chave é o que entra no estado.

        Com `chave`, a gravação fica idempotente: o mesmo `wamid` regrava o
        mesmo objeto em vez de deixar um órfão a cada reenvio da Meta.
        """
        ...

    def ler(self, chave: str) -> bytes: ...

    def apagar(self, chave: str) -> None: ...


def criar_storage(settings: Settings) -> Storage:
    """S3 quando há bucket; memória em `pytest`.

    O `cast` é explícito de propósito: a conformidade com o protocolo é checada
    pelo `mypy` (strict) e exercitada pelos testes das duas implementações, e
    some com a inferência estrutural de ferramenta que não acompanha o arquivo.
    """

    if settings.environment == "pytest" or not settings.s3_bucket:
        return cast(Storage, MemoriaStorage())
    return cast(Storage, S3Storage(settings))
