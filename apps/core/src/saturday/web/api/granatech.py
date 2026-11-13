"""Webhook da Granatech (eventos de consulta e de proposta).

A Granatech não assina o corpo: a autenticação é um token longo, aceito em
``?t=``, ``Authorization: Bearer`` ou ``x-webhook-token`` e comparado em tempo
constante. A query string não vai para o access log (``SemQueryString``).

Como o webhook do WhatsApp: grava, responde 200 e deixa o worker processar.
Sem id de evento no payload, a deduplicação usa o hash do JSON canônico.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session, sessionmaker

from saturday.dados.eventos import enfileirar
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.settings import Settings
from saturday.web.dependencies import get_fabrica, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["granatech"])

ORIGEM = "granatech"


def token_recebido(request: Request) -> str:
    autorizacao = request.headers.get("authorization", "")
    if autorizacao.lower().startswith("bearer "):
        return autorizacao[7:].strip()
    return request.headers.get("x-webhook-token") or request.query_params.get("t") or ""


def impressao(token: str) -> str:
    """8 primeiros hex do SHA-256: compara tokens sem expor nenhum dos dois."""

    return hashlib.sha256(token.encode()).hexdigest()[:8] if token else ""


def diagnostico(request: Request, corpo: bytes, esperado: str) -> dict[str, Any]:
    """O que veio numa chamada recusada, para dizer à Granatech o que mudar.

    Nunca o token nem a query string: só por onde o token veio, o tamanho e a
    impressão (`impressao`), os nomes dos cabeçalhos e as chaves do corpo (o
    corpo da consulta traz CPF).
    """

    autorizacao = request.headers.get("authorization", "")
    fontes = []
    if autorizacao.lower().startswith("bearer "):
        fontes.append("authorization_bearer")
    elif autorizacao:
        # Token cru ou outro esquema (Basic, Token...): não é aceito.
        # Só o nome do esquema (Basic, Token...); sem espaço é o token cru, que
        # não pode ir para o log nem em parte.
        esquema, _, resto = autorizacao.partition(" ")
        nome = esquema[:12] if resto and esquema.isalpha() else "cru"
        fontes.append(f"authorization_sem_bearer:{nome}")
    if "x-webhook-token" in request.headers:
        fontes.append("x-webhook-token")
    if "t" in request.query_params:
        fontes.append("query_t")
    recebido = token_recebido(request)
    try:
        payload = json.loads(corpo)
    except ValueError:
        payload = None
    chaves = sorted(payload) if isinstance(payload, dict) else []
    return {
        "token_fontes": fontes or ["nenhuma"],
        "token_tamanho": len(recebido),
        "token_esperado_tamanho": len(esperado),
        "token_impressao": impressao(recebido),
        "token_esperado_impressao": impressao(esperado),
        "token_com_espacos": recebido != recebido.strip(),
        "token_bate_sem_espacos": bool(recebido)
        and hmac.compare_digest(recebido.strip().encode(), esperado.encode()),
        # Token cru em Authorization (sem "Bearer "): diz se trocar o formato resolve.
        "authorization_cru_bate": bool(autorizacao)
        and not autorizacao.lower().startswith("bearer ")
        and hmac.compare_digest(autorizacao.strip().encode(), esperado.encode()),
        "query_parametros": sorted(request.query_params.keys()),
        "cabecalhos": sorted(request.headers.keys()),
        "content_type": request.headers.get("content-type", ""),
        "user_agent": request.headers.get("user-agent", "")[:120],
        "corpo_bytes": len(corpo),
        "corpo_json": payload is not None,
        "corpo_chaves": chaves[:30],
        "corpo_tipo": str(payload.get("tipo", ""))[:40] if isinstance(payload, dict) else "",
    }


def evento_id(payload: dict[str, Any]) -> str:
    """Mesmo evento reenviado = mesmo id, independente da ordem das chaves."""

    canonico = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonico.encode()).hexdigest()


@router.post("/webhooks/granatech", status_code=200)
async def receber(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    fabrica: Annotated[sessionmaker[Session] | None, Depends(get_fabrica)],
) -> Response:
    esperado = settings.granatech_webhook_token.get_secret_value()
    if not esperado:
        # Token vazio nunca vale como senha: recusa tudo até ser configurado.
        raise HTTPException(status_code=503, detail="webhook não configurado")

    recebido = token_recebido(request)
    if not hmac.compare_digest(recebido.encode(), esperado.encode()):
        logger.warning(
            "granatech_token_invalido",
            extra=diagnostico(request, await request.body(), esperado),
        )
        raise HTTPException(status_code=401, detail="token inválido")

    try:
        payload = json.loads(await request.body())
    except ValueError:
        raise HTTPException(status_code=400, detail="corpo inválido") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="corpo inválido")

    if fabrica is not None:
        with abrir_sessao(fabrica) as sessao:
            enfileirar(sessao, origem=ORIGEM, evento_id=evento_id(payload), payload=payload)
    return Response(status_code=200)
