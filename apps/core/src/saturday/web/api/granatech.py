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
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from saturday.dados.eventos import enfileirar
from saturday.dados.modelos import EventoRecebido
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.privacidade import mascarar_cpf
from saturday.settings import Settings
from saturday.web.dependencies import exigir_fabrica, get_fabrica, get_settings, verificar_api_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["granatech"])

ORIGEM = "granatech"


def token_recebido(request: Request) -> str:
    autorizacao = request.headers.get("authorization", "")
    if autorizacao.lower().startswith("bearer "):
        return autorizacao[7:].strip()
    return request.headers.get("x-webhook-token") or request.query_params.get("t") or ""


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
        logger.warning("granatech_token_invalido")
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


@router.get("/eventos/granatech/{id_externo}", dependencies=[Depends(verificar_api_key)])
def eventos_recebidos(
    id_externo: str,
    fabrica: Annotated[sessionmaker[Session], Depends(exigir_fabrica)],
) -> list[dict[str, Any]]:
    """Eventos da Granatech recebidos para uma consulta ou proposta.

    Evidência de webhook para a homologação (``scripts/homologacao_granatech.py``),
    que roda fora do servidor e não enxerga o banco. O CPF sai mascarado.
    """

    with abrir_sessao(fabrica) as sessao:
        linhas = sessao.scalars(
            select(EventoRecebido)
            .where(
                EventoRecebido.origem == ORIGEM,
                or_(
                    EventoRecebido.payload["id_solicitacao"].astext == id_externo,
                    EventoRecebido.payload["id_proposta"].astext == id_externo,
                ),
            )
            .order_by(EventoRecebido.id)
        ).all()
        return [
            {
                "recebido_em": linha.recebido_em.isoformat(),
                "processado_em": linha.processado_em.isoformat() if linha.processado_em else None,
                "payload": {
                    **(linha.payload or {}),
                    "cpf": mascarar_cpf(str((linha.payload or {}).get("cpf") or "")),
                },
            }
            for linha in linhas
        ]
