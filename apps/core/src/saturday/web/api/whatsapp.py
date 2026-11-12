"""Webhook da WhatsApp Cloud API.

A regra do projeto: gravar, responder 200 rápido e deixar o worker processar.
A Meta reenvia o evento se a resposta demorar ou não for 2xx, então o turno não
pode acontecer aqui.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.orm import Session, sessionmaker

from saturday.canais.whatsapp import webhook as parser
from saturday.dados.eventos import enfileirar
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.settings import Settings
from saturday.web.dependencies import get_fabrica, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["whatsapp"])

ORIGEM = "whatsapp"


def assinatura_valida(corpo: bytes, cabecalho: str | None, segredo: str) -> bool:
    """`X-Hub-Signature-256` é `sha256=` + HMAC-SHA256 do corpo cru.

    A comparação é em tempo constante: comparar com `==` vaza o prefixo correto
    pelo tempo de resposta.
    """

    if not cabecalho or not segredo:
        return False
    if not cabecalho.startswith("sha256="):
        return False

    esperado = hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()
    recebido = cabecalho.removeprefix("sha256=")
    return hmac.compare_digest(recebido, esperado)


@router.get("/webhooks/whatsapp", response_class=PlainTextResponse)
def verificar(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> PlainTextResponse:
    """Verificação que a Meta faz uma vez ao cadastrar a URL."""

    parametros = request.query_params
    if parametros.get("hub.mode") != "subscribe":
        raise HTTPException(status_code=403, detail="modo inválido")

    esperado = settings.whatsapp_verify_token.get_secret_value()
    recebido = parametros.get("hub.verify_token", "")
    if not esperado or not hmac.compare_digest(recebido, esperado):
        raise HTTPException(status_code=403, detail="token inválido")

    return PlainTextResponse(parametros.get("hub.challenge", ""))


@router.post("/webhooks/whatsapp", status_code=200)
async def receber(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    fabrica: Annotated[sessionmaker[Session] | None, Depends(get_fabrica)],
) -> Response:
    """Grava os eventos e responde 200. Nunca roda turno aqui."""

    corpo = await request.body()
    segredo = settings.whatsapp_app_secret.get_secret_value()
    if not assinatura_valida(corpo, request.headers.get("x-hub-signature-256"), segredo):
        logger.warning("whatsapp_assinatura_invalida")
        raise HTTPException(status_code=401, detail="assinatura inválida")

    try:
        payload = json.loads(corpo)
    except ValueError:
        raise HTTPException(status_code=400, detail="corpo inválido") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="corpo inválido")

    encontrados = parser.eventos(payload)
    aceitos = _dos_numeros_configurados(encontrados, settings)

    if fabrica is not None and aceitos:
        _gravar(fabrica, aceitos)

    # 200 mesmo sem evento: a Meta não deve reenviar por falta de interesse nosso.
    return Response(status_code=200)


def _dos_numeros_configurados(
    encontrados: list[parser.Evento],
    settings: Settings,
) -> list[parser.Evento]:
    """Só os números ativos; evento de outro número é ignorado, não é erro."""

    ativos = set(settings.whatsapp_numeros)
    if not ativos:
        return encontrados
    return [evento for evento in encontrados if evento.phone_number_id in ativos]


def _gravar(fabrica: sessionmaker[Session], aceitos: list[parser.Evento]) -> None:
    with abrir_sessao(fabrica) as sessao:
        for evento in aceitos:
            enfileirar(
                sessao,
                origem=ORIGEM,
                evento_id=evento.evento_id,
                payload=para_dict(evento),
            )


def para_dict(evento: parser.Evento) -> dict[str, Any]:
    midia = None
    if evento.midia is not None:
        midia = {"id": evento.midia.id, "mime_type": evento.midia.mime_type}
        if evento.midia.nome:
            midia["nome"] = evento.midia.nome

    return {
        "tipo": evento.tipo,
        "evento_id": evento.evento_id,
        "wamid": evento.wamid,
        "numero": evento.numero,
        "phone_number_id": evento.phone_number_id,
        "texto": evento.texto,
        "tipo_midia": evento.tipo_midia,
        "midia": midia,
        "status": evento.status,
        "referral": evento.referral,
        "roda_turno": evento.roda_turno,
    }
