"""Contrato do canal de atendimento.

A origem diz *de onde* veio o turno (e por onde a resposta tem que sair); o
protocolo `Canal` é o que o worker usa para entregar, sem saber se é webhook,
WhatsApp ou o que vier depois.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class OrigemCanal:
    """De onde veio a mensagem do cliente."""

    canal: str = "chat"
    telefone: str | None = None
    phone_number_id: str | None = None


class Canal(Protocol):
    """Entrega de uma resposta ao cliente."""

    def janela_aberta(self, conversation_id: str, agora: datetime) -> bool: ...

    def entregar_texto(self, numero: str, phone_number_id: str, texto: str) -> str | None: ...

    def entregar_modelo(
        self,
        numero: str,
        phone_number_id: str,
        *,
        parametros: list[str],
        sufixo_link: str | None = None,
    ) -> str | None: ...
