"""Simulador da Evolution API (v2.3.7, integração Baileys).

Pequeno de propósito: emula o que o Saturday usa (decisões 0009 e 0010).
Envio de texto, download de mídia em base64, gestão de instâncias em memória e
um admin para injetar mensagem de cliente, disparar status de entrega e de
conexão e forçar falha.

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
# nome → {"estado": open|connecting|close, "telefone": "55...", "webhook": {...}}
INSTANCIAS: dict[str, dict[str, Any]] = {}
QR_FALSO = "data:image/png;base64,iVBORw0KGgo="

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
    INSTANCIAS.clear()
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


# ------------------------------------------------------------ instâncias (0010)


@app.post("/instance/create")
async def criar_instancia(request: Request) -> Any:
    if not _autorizado(request):
        return _erro(401, "Unauthorized")
    corpo = await request.json()
    nome = str(corpo.get("instanceName") or "")
    if corpo.get("integration") != "WHATSAPP-BAILEYS":
        return _erro(400, ["Invalid integration"])
    if nome in INSTANCIAS:
        return _erro(403, [f'This name "{nome}" is already in use.'])
    INSTANCIAS[nome] = {"estado": "connecting", "telefone": "", "webhook": corpo.get("webhook")}
    return JSONResponse(
        status_code=201,
        content={
            "instance": {"instanceName": nome, "status": "connecting"},
            "qrcode": {"base64": QR_FALSO, "code": "sim", "count": 1},
        },
    )


@app.get("/instance/connect/{nome}")
def conectar(nome: str, request: Request) -> Any:
    if not _autorizado(request):
        return _erro(401, "Unauthorized")
    if nome not in INSTANCIAS:
        return _erro(404, [f'The "{nome}" instance does not exist'])
    instancia = INSTANCIAS[nome]
    if instancia["estado"] == "open":
        return {"instance": {"instanceName": nome, "state": "open"}}
    instancia["estado"] = "connecting"
    return {"base64": QR_FALSO, "code": "sim", "count": 1}


@app.get("/instance/fetchInstances")
def listar_instancias(request: Request) -> Any:
    if not _autorizado(request):
        return _erro(401, "Unauthorized")
    return [
        {
            "name": nome,
            "connectionStatus": dados["estado"],
            "ownerJid": f"{dados['telefone']}@s.whatsapp.net" if dados["telefone"] else None,
        }
        for nome, dados in INSTANCIAS.items()
    ]


@app.delete("/instance/logout/{nome}")
def desconectar(nome: str, request: Request) -> Any:
    if not _autorizado(request):
        return _erro(401, "Unauthorized")
    instancia = INSTANCIAS.get(nome)
    if instancia is None or instancia["estado"] == "close":
        return _erro(400, [f'The "{nome}" instance is not connected'])
    instancia["estado"] = "close"
    return {"status": "SUCCESS", "error": False, "response": {"message": "Instance logged out"}}


@app.delete("/instance/delete/{nome}")
def apagar_instancia(nome: str, request: Request) -> Any:
    if not _autorizado(request):
        return _erro(401, "Unauthorized")
    if INSTANCIAS.pop(nome, None) is None:
        return _erro(404, [f'The "{nome}" instance does not exist'])
    return {"status": "SUCCESS", "error": False, "response": {"message": "Instance deleted"}}


@app.post("/webhook/set/{nome}")
async def configurar_webhook(nome: str, request: Request) -> Any:
    if not _autorizado(request):
        return _erro(401, "Unauthorized")
    if nome not in INSTANCIAS:
        return _erro(404, [f'The "{nome}" instance does not exist'])
    INSTANCIAS[nome]["webhook"] = (await request.json()).get("webhook")
    return JSONResponse(status_code=201, content={"webhook": INSTANCIAS[nome]["webhook"]})


@app.post("/settings/set/{nome}")
async def configurar(nome: str, request: Request) -> Any:
    if not _autorizado(request):
        return _erro(401, "Unauthorized")
    corpo = await request.json()
    obrigatorios = (
        "rejectCall",
        "groupsIgnore",
        "alwaysOnline",
        "readMessages",
        "readStatus",
        "syncFullHistory",
    )
    faltando = [campo for campo in obrigatorios if campo not in corpo]
    if faltando:
        return _erro(400, [f"{campo} is required" for campo in faltando])
    return JSONResponse(status_code=201, content={"settings": corpo})


@app.post("/admin/conexao")
async def disparar_conexao(request: Request) -> JSONResponse:
    """`{"instancia": "mex-sim", "estado": "open", "telefone": "5511..."}`."""

    corpo = await request.json()
    nome = str(corpo.get("instancia") or INSTANCIA)
    estado = str(corpo.get("estado") or "open")
    telefone = str(corpo.get("telefone") or NUMERO)
    INSTANCIAS.setdefault(nome, {"estado": estado, "telefone": "", "webhook": None})
    INSTANCIAS[nome]["estado"] = estado
    dados: dict[str, Any] = {"instance": nome, "state": estado, "statusReason": 200}
    if estado == "open":
        INSTANCIAS[nome]["telefone"] = telefone
        dados["wuid"] = f"{telefone}@s.whatsapp.net"
    payload = {"event": "connection.update", "instance": nome, "data": dados}
    destino = f"{SATURDAY_URL.rstrip('/')}/webhooks/evolution"
    async with httpx.AsyncClient(timeout=10.0) as cliente:
        resposta = await cliente.post(
            destino, json=payload, headers={"x-webhook-token": WEBHOOK_TOKEN}
        )
    return JSONResponse(content={"saturday_status": resposta.status_code})
