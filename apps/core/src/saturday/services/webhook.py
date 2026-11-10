"""Envio do evento ao webhook configurado."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx

from saturday.metrics import registrar_chamada
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
        inicio = time.monotonic()
        try:
            corpo = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            timestamp = str(int(time.time()))
            segredo = self._settings.webhook_secret.get_secret_value()
            assinatura = hmac.new(
                segredo.encode("utf-8"),
                f"{timestamp}.".encode() + corpo,
                hashlib.sha256,
            ).hexdigest()
            response = self._http.post(
                self._settings.webhook_url,
                content=corpo,
                headers={
                    "Content-Type": "application/json",
                    "X-Saturday-Timestamp": timestamp,
                    "X-Saturday-Signature": f"sha256={assinatura}",
                },
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
        finally:
            registrar_chamada("webhook", (time.monotonic() - inicio) * 1000)
