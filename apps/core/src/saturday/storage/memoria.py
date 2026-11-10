"""Storage em memória, usado nos testes e no ambiente ``pytest``."""

from __future__ import annotations

import uuid


class MemoriaStorage:
    """Mesmo contrato do S3, sem rede. Vive enquanto o processo viver."""

    def __init__(self) -> None:
        self._objetos: dict[str, bytes] = {}

    def salvar(self, dados: bytes, *, mime_type: str) -> str:
        chave = f"anexos/{uuid.uuid4().hex}"
        self._objetos[chave] = dados
        return chave

    def ler(self, chave: str) -> bytes:
        return self._objetos[chave]

    def apagar(self, chave: str) -> None:
        self._objetos.pop(chave, None)

    def existe(self, chave: str) -> bool:
        return chave in self._objetos
