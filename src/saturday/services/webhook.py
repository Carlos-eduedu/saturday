"""Envio do evento ao webhook configurado."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from saturday.settings import WEBHOOK_TIMEOUT_S, get_settings

logger = logging.getLogger(__name__)


def send(payload: dict[str, Any]) -> bool:
    """Uma única tentativa. Nunca levanta exceção para o chamador."""

    webhook_url = get_settings().webhook_url
    if not webhook_url:
        return False

    conversation_id = payload.get("conversation_id")
    status = payload.get("status")
    try:
        response = httpx.post(webhook_url, json=payload, timeout=WEBHOOK_TIMEOUT_S)
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
