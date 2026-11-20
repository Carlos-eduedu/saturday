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
from saturday.privacidade import mascarar_conversation_id
from saturday.settings import WEBHOOK_TIMEOUT_S, Settings

logger = logging.getLogger(__name__)


def corpo_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def cabecalhos_assinados(segredo: str, corpo: bytes) -> dict[str, str]:
    """`X-Saturday-Signature` = HMAC-SHA256 de ``"<timestamp>." + corpo``."""

    timestamp = str(int(time.time()))
    assinatura = hmac.new(
        segredo.encode("utf-8"), f"{timestamp}.".encode() + corpo, hashlib.sha256
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-Saturday-Timestamp": timestamp,
        "X-Saturday-Signature": f"sha256={assinatura}",
    }


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
            corpo = corpo_json(payload)
            response = self._http.post(
                self._settings.webhook_url,
                content=corpo,
                headers=cabecalhos_assinados(
                    self._settings.webhook_secret.get_secret_value(), corpo
                ),
                timeout=WEBHOOK_TIMEOUT_S,
            )
            response.raise_for_status()
            return True
        except Exception as exc:
            # Nunca logar o conteúdo do payload: ele pode conter dados pessoais.
            logger.error(
                "webhook_falhou conversation_id=%s status=%s erro=%s",
                mascarar_conversation_id(str(conversation_id)),
                status,
                type(exc).__name__,
            )
            return False
        finally:
            registrar_chamada("webhook", (time.monotonic() - inicio) * 1000)
