"""Contrato do canal de atendimento.

A origem diz *de onde* veio o turno (e por onde a resposta tem que sair); o
protocolo `Canal` é o que o worker usa para entregar, sem saber se é webhook,
WhatsApp ou o que vier depois.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class Resultado(StrEnum):
    """O que o canal sabe sobre uma tentativa de entrega.

    O canal classifica e para; quem decide esperar ou desistir é o outbox.
    """

    OK = "ok"
    TEMPORARIO = "temporario"
    # A requisição pode ter sido aceita (timeout de leitura): repetir às cegas
    # duplicaria a mensagem, porque a Meta não tem chave de idempotência.
    TEMPORARIO_INCERTO = "temporario_incerto"
    PERMANENTE = "permanente"
    # A Meta recusou texto porque a janela fechou; o outbox converte para modelo.
    JANELA_FECHADA = "janela_fechada"


@dataclass(frozen=True)
class OrigemCanal:
    """De onde veio a mensagem do cliente."""

    canal: str = "chat"
    telefone: str | None = None
    phone_number_id: str | None = None


class Canal(Protocol):
    """Entrega de uma resposta ao cliente. Não repete nada."""

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
