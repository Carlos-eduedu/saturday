"""Webhook do motor de consultas do iCred (decisão 0027).

O motor assina o corpo: ``X-Icred-Assinatura`` é
``sha256=HMAC-SHA256(segredo, "<X-Icred-Timestamp>.<corpo bruto>")``, conferido
em tempo constante. Timestamp com mais de 5 minutos é recusado.

Como os outros webhooks: grava, responde 200 e deixa o worker processar. A
deduplicação usa o ``X-Icred-Id``, que o motor repete nas reentregas.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session, sessionmaker

from saturday.dados.eventos import enfileirar
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.settings import Settings
from saturday.web.dependencies import get_fabrica, get_settings

router = APIRouter(tags=["icred"])

ORIGEM = "icred"
TOLERANCIA_S = 300


def assinatura_valida(corpo: bytes, timestamp: str, assinatura: str, segredo: str) -> bool:
    mac = hmac.new(segredo.encode(), timestamp.encode() + b"." + corpo, hashlib.sha256)
    return hmac.compare_digest(("sha256=" + mac.hexdigest()).encode(), assinatura.encode())


@router.post("/webhooks/icred", status_code=200)
async def receber(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    fabrica: Annotated[sessionmaker[Session], Depends(get_fabrica)],
) -> Response:
    segredo = settings.icred_webhook_segredo.get_secret_value()
    if not segredo:
        # Segredo vazio nunca vale como assinatura: recusa tudo até ser configurado.
        raise HTTPException(status_code=503, detail="webhook não configurado")

    corpo = await request.body()
    timestamp = request.headers.get("X-Icred-Timestamp", "")
    assinatura = request.headers.get("X-Icred-Assinatura", "")
    if not assinatura_valida(corpo, timestamp, assinatura, segredo):
        raise HTTPException(status_code=401, detail="assinatura inválida")
    if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > TOLERANCIA_S:
        raise HTTPException(status_code=401, detail="timestamp fora da janela")

    try:
        payload = json.loads(corpo)
    except ValueError:
        raise HTTPException(status_code=400, detail="corpo inválido") from None
    evento_id = request.headers.get("X-Icred-Id") or ""
    if not isinstance(payload, dict) or not evento_id:
        raise HTTPException(status_code=400, detail="corpo inválido")

    with abrir_sessao(fabrica) as sessao:
        enfileirar(sessao, origem=ORIGEM, evento_id=evento_id, payload=payload)
    return Response(status_code=200)
