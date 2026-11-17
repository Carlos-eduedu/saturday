"""Logging estruturado em JSON, sem dados pessoais."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote

from saturday.privacidade import mascarar_conversation_id

# Campos que o próprio ``logging`` adiciona ao registro e que não são ``extra``.
_RESERVADOS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "asctime",
    "message",
    "taskName",
}


# O httpx registra em INFO a URL inteira de cada chamada, e a query da consulta
# da Granatech leva CPF, nome e telefone (regra 9). Rota, status e tempo já saem
# no log de cada cliente.
LOGGERS_SO_AVISOS = ("httpx", "httpx2")


class JsonFormatter(logging.Formatter):
    """Uma linha JSON por registro, com os campos passados em ``extra``."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for chave, valor in record.__dict__.items():
            if chave not in _RESERVADOS and chave not in payload:
                payload[chave] = valor
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class SemQueryString(logging.Filter):
    """Corta a query do access log: busca por telefone e tokens viajam nela.

    No caminho, mascara o telefone de um `conversation_id` do WhatsApp
    (`/conversations/whatsapp:<telefone>`).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Formato do uvicorn: (cliente, método, caminho, versão, status).
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            # O uvicorn codifica o caminho: sem o `unquote`, o `:` chega como `%3A`.
            caminho = mascarar_conversation_id(unquote(args[2].split("?", 1)[0]))
            record.args = (*args[:2], caminho, *args[3:])
        return True


def configurar_logging(nivel: str) -> None:
    """Configura o logger raiz e os do uvicorn com o mesmo handler e cala o httpx."""

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    raiz = logging.getLogger()
    raiz.setLevel(nivel.upper())
    raiz.handlers.clear()
    raiz.addHandler(handler)
    for nome in LOGGERS_SO_AVISOS:
        logging.getLogger(nome).setLevel(logging.WARNING)

    for nome in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(nome)
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.propagate = False
    acesso = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, SemQueryString) for f in acesso.filters):
        acesso.addFilter(SemQueryString())
