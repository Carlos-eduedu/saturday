"""Envio do evento ao webhook configurado."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from saturday.settings import WEBHOOK_TIMEOUT_S, Settings

logger = logging.getLogger(__name__)


class WebhookClient:
    """Envia eventos ao webhook com o cliente HTTP compartilhado."""

    def __init__(self, http: httpx.Client, settings: Settings) -> None:
        self._http = http
        self._settings = settings

    @property
    def configurado(self) -> bool:
        return bool(self._settings.webhook_url)

    def enviar(self, payload: dict[str, Any]) -> bool:
        """Uma única tentativa. Nunca levanta exceção para o chamador."""

        if not self._settings.webhook_url:
            return False

        conversation_id = payload.get("conversation_id")
        status = payload.get("status")
        try:
            response = self._http.post(
                self._settings.webhook_url,
                json=payload,
                timeout=WEBHOOK_TIMEOUT_S,
            )
            response.raise_for_status()
            return True
        except Exception as exc:
            # Nunca logar o conteúdo do payload: ele pode conter dados pessoais.
            logger.error(
                "webhook_falhou conversation_id=%s status=%s erro=%s",
                conversation_id,
                status,
                type(exc).__name__,
            )
            return False
