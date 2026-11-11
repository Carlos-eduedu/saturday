"""Simulador da WhatsApp Cloud API.

Pequeno de propósito: emula o que o Saturday usa. Envio de texto e modelo,
metadados e download de mídia, e um admin para injetar mensagem de cliente e
forçar falha.

Rodar local:
    uvicorn app:app --app-dir simuladores/meta --port 8100
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

app = FastAPI(title="Simulador da Meta", version="0.1.0")

ENVIADAS: list[dict[str, Any]] = []
LIDAS: list[dict[str, Any]] = []
MIDIAS: dict[str, tuple[bytes, str]] = {}
FALHAS: list[dict[str, Any]] = []
CONTADOR = {"wamid": 0}

SATURDAY_URL = os.environ.get("SIMULADOR_SATURDAY_URL", "http://api:8000")
APP_SECRET = os.environ.get("SATURDAY_WHATSAPP_APP_SECRET", "segredo-do-simulador")
NUMERO = os.environ.get("SIMULADOR_WHATSAPP_NUMERO", "11987654321")
PHONE_NUMBER_ID = os.environ.get("SIMULADOR_PHONE_NUMBER_ID", "100000000000001")


def _proximo_wamid() -> str:
    CONTADOR["wamid"] += 1
    return f"wamid.sim.{CONTADOR['wamid']}"


@app.post("/{phone_number_id}/messages")
async def enviar(phone_number_id: str, request: Request) -> Any:
    """Envio de texto ou modelo. Consome uma falha programada, se houver."""

    corpo = await request.json()
    if FALHAS:
        falha = FALHAS.pop(0)
        return JSONResponse(
            status_code=int(falha.get("status", 500)),
            content={"error": {"code": falha.get("code"), "message": "falha simulada"}},
        )

    if corpo.get("status") == "read":
        LIDAS.append({"phone_number_id": phone_number_id, "message_id": corpo.get("message_id")})
        return {"success": True}

    wamid = _proximo_wamid()
    ENVIADAS.append({"phone_number_id": phone_number_id, "wamid": wamid, **corpo})
    return {"messages": [{"id": wamid}]}


@app.get("/admin/enviadas")
def listar_enviadas() -> dict[str, Any]:
    return {"enviadas": ENVIADAS}


@app.get("/admin/lidas")
def listar_lidas() -> dict[str, Any]:
    return {"lidas": LIDAS}


@app.post("/admin/limpar")
def limpar() -> dict[str, int]:
    ENVIADAS.clear()
    LIDAS.clear()
    MIDIAS.clear()
    FALHAS.clear()
    return {"ok": 1}


@app.post("/admin/falhas")
async def programar_falha(request: Request) -> dict[str, Any]:
    FALHAS.append(await request.json())
    return {"programadas": len(FALHAS)}


@app.post("/admin/midia")
async def criar_midia(request: Request, mime: str = "application/octet-stream") -> dict[str, str]:
    """Guarda bytes que o Saturday vai buscar pelo `media_id`."""

    identificador = uuid.uuid4().hex
    MIDIAS[identificador] = (await request.body(), mime)
    return {"id": identificador, "mime_type": mime}


@app.get("/{media_id}")
def metadados_midia(media_id: str) -> Any:
    if media_id not in MIDIAS:
        return JSONResponse(status_code=404, content={"error": {"code": 100}})
    dados, mime = MIDIAS[media_id]
    return {
        "url": f"{_base()}/media/{media_id}",
        "mime_type": mime,
        "file_size": len(dados),
    }


@app.get("/media/{media_id}")
def bytes_midia(media_id: str) -> Response:
    if media_id not in MIDIAS:
        return JSONResponse(status_code=404, content={"error": {"code": 100}})
    dados, mime = MIDIAS[media_id]
    return Response(content=dados, media_type=mime)


def _base(request: Request | None = None) -> str:
    if request is not None:
        return str(request.base_url).rstrip("/")
    return os.environ.get("SIMULADOR_BASE_URL", "http://meta:8100")


@app.post("/admin/mensagem")
async def injetar_mensagem(request: Request) -> Response:
    """Monta o webhook da Meta e entrega no Saturday, já assinado."""

    corpo = await request.json()
    tipo = str(corpo.get("tipo") or "text")
    texto = str(corpo.get("texto") or "")
    media_id = corpo.get("media_id")

    mensagem: dict[str, Any] = {
        "id": _proximo_wamid(),
        "from": str(corpo.get("numero") or NUMERO),
        "timestamp": "1700000000",
        "type": tipo,
    }
    if tipo == "text":
        mensagem["text"] = {"body": texto}
    else:
        mensagem[tipo] = {
            "id": media_id,
            "mime_type": corpo.get("mime_type"),
            "filename": corpo.get("filename"),
        }
        if texto:
            mensagem[tipo]["caption"] = texto

    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "sim",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"phone_number_id": PHONE_NUMBER_ID},
                            "messages": [mensagem],
                        },
                    }
                ],
            }
        ],
    }

    cru = json.dumps(payload).encode()
    assinatura = "sha256=" + hmac.new(APP_SECRET.encode(), cru, hashlib.sha256).hexdigest()
    destino = f"{SATURDAY_URL.rstrip('/')}/webhooks/whatsapp"

    async with httpx.AsyncClient(timeout=10.0) as cliente:
        resposta = await cliente.post(
            destino,
            content=cru,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": assinatura,
            },
        )
    return JSONResponse(
        status_code=resposta.status_code,
        content={
            "wamid": mensagem["id"],
            "saturday_status": resposta.status_code,
        },
    )
