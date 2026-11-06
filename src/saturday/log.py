"""Logging estruturado em JSON, sem dados pessoais."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Campos que o próprio ``logging`` adiciona ao registro e que não são ``extra``.
_RESERVADOS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "asctime",
    "message",
    "taskName",
}


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


def configurar_logging(nivel: str) -> None:
    """Configura o logger raiz e os loggers do uvicorn com o mesmo handler."""

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    raiz = logging.getLogger()
    raiz.setLevel(nivel.upper())
    raiz.handlers.clear()
    raiz.addHandler(handler)

    for nome in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(nome)
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.propagate = False
