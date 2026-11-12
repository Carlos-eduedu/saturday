"""Simulador da Evolution API (v2.3.7, integração Baileys).

Pequeno de propósito: emula o que o Saturday usa (decisão 0009). Envio de
texto, download de mídia em base64 e um admin para injetar mensagem de
cliente, disparar status de entrega e forçar falha.

Rodar local:
    uvicorn app:app --app-dir simuladores/evolution --port 8300
"""

from __future__ import annotations

import base64
import os
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Simulador da Evolution", version="0.1.0")

ENVIADAS: list[dict[str, Any]] = []
MIDIAS: dict[str, tuple[bytes, str]] = {}
FALHAS: list[dict[str, Any]] = []

SATURDAY_URL = os.environ.get("SIMULADOR_SATURDAY_URL", "http://api:8000")
API_KEY = os.environ.get("SATURDAY_EVOLUTION_API_KEY", "chave-do-simulador")
WEBHOOK_TOKEN = os.environ.get("SATURDAY_EVOLUTION_WEBHOOK_TOKEN", "token-do-simulador")
INSTANCIA = os.environ.get("SIMULADOR_EVOLUTION_INSTANCIA", "mex-sim")
NUMERO = os.environ.get("SIMULADOR_EVOLUTION_NUMERO", "5511987654321")


def _id() -> str:
    return "3EB0" + uuid.uuid4().hex[:16].upper()


def _erro(status: int, mensagem: Any) -> JSONResponse:
    """Envelope de erro da Evolution: `{status, error, response: {message}}`."""

    return JSONResponse(
        status_code=status,
        content={"status": status, "error": "Bad Request", "response": {"message": mensagem}},
    )


def _autorizado(request: Request) -> bool:
    return request.headers.get("apikey") == API_KEY


@app.post("/message/sendText/{instancia}")
async def enviar_texto(instancia: str, request: Request) -> Any:
    """Consome uma falha programada, se houver; senão responde 201 com `key.id`."""

    if not _autorizado(request):
        return _erro(401, "Unauthorized")
    corpo = await request.json()
    if FALHAS:
        falha = FALHAS.pop(0)
        status = int(falha.get("status", 500))
        if falha.get("inexistente"):
            return _erro(400, [{"jid": "", "exists": False, "number": corpo.get("number")}])
        return _erro(status, ["Error: falha simulada"])

    identificador = _id()
    ENVIADAS.append({"instancia": instancia, "id": identificador, **corpo})
    return JSONResponse(
        status_code=201,
        content={
            "key": {
                "remoteJid": f"{corpo.get('number')}@s.whatsapp.net",
                "fromMe": True,
                "id": identificador,
            },
            "status": "PENDING",
            "message": {"conversation": corpo.get("text")},
            "messageType": "conversation",
        },
    )


@app.post("/chat/getBase64FromMediaMessage/{instancia}")
async def baixar_midia(instancia: str, request: Request) -> Any:
    if not _autorizado(request):
        return _erro(401, "Unauthorized")
    corpo = await request.json()
    identificador = str(((corpo.get("message") or {}).get("key") or {}).get("id") or "")
    if identificador not in MIDIAS:
        return _erro(400, ["Message not found"])
    dados, mime = MIDIAS[identificador]
    return JSONResponse(
        status_code=201,
        content={"mimetype": mime, "base64": base64.b64encode(dados).decode()},
    )


@app.get("/admin/enviadas")
def listar_enviadas() -> dict[str, Any]:
    return {"enviadas": ENVIADAS}


@app.post("/admin/limpar")
def limpar() -> dict[str, int]:
    ENVIADAS.clear()
    MIDIAS.clear()
    FALHAS.clear()
    return {"ok": 1}


@app.post("/admin/falhas")
async def programar_falha(request: Request) -> dict[str, Any]:
    """`{"status": 500}` ou `{"inexistente": true}` (número sem WhatsApp)."""

    FALHAS.append(await request.json())
    return {"programadas": len(FALHAS)}


async def _entregar(evento: str, dados: dict[str, Any]) -> JSONResponse:
    payload = {"event": evento, "instance": INSTANCIA, "data": dados}
    destino = f"{SATURDAY_URL.rstrip('/')}/webhooks/evolution"
    async with httpx.AsyncClient(timeout=10.0) as cliente:
        resposta = await cliente.post(
            destino, json=payload, headers={"x-webhook-token": WEBHOOK_TOKEN}
        )
    return JSONResponse(
        content={
            "id": dados.get("key", {}).get("id") or dados.get("keyId"),
            "saturday_status": resposta.status_code,
        }
    )


@app.post("/admin/mensagem")
async def injetar_mensagem(request: Request) -> JSONResponse:
    """Mensagem do cliente: `texto`, ou `tipo` de mídia com os bytes em `base64`."""

    corpo = await request.json()
    identificador = _id()
    tipo = str(corpo.get("tipo") or "conversation")
    texto = str(corpo.get("texto") or "")
    mensagem: dict[str, Any]
    if tipo == "conversation":
        mensagem = {"conversation": texto}
    else:
        mime = str(corpo.get("mime_type") or "application/octet-stream")
        MIDIAS[identificador] = (base64.b64decode(str(corpo.get("base64") or "")), mime)
        mensagem = {tipo: {"mimetype": mime, "caption": texto, "fileName": corpo.get("filename")}}

    numero = str(corpo.get("numero") or NUMERO)
    return await _entregar(
        "messages.upsert",
        {
            "key": {
                "remoteJid": f"{numero}@s.whatsapp.net",
                "fromMe": False,
                "id": identificador,
            },
            "pushName": "Cliente",
            "message": mensagem,
            "messageType": tipo,
            "messageTimestamp": 1700000000,
        },
    )


@app.post("/admin/status")
async def disparar_status(request: Request) -> JSONResponse:
    """`{"id": "<key.id do envio>", "status": "DELIVERY_ACK"}`."""

    corpo = await request.json()
    return await _entregar(
        "messages.update",
        {
            "keyId": corpo.get("id"),
            "remoteJid": f"{NUMERO}@s.whatsapp.net",
            "fromMe": True,
            "status": corpo.get("status", "DELIVERY_ACK"),
        },
    )
