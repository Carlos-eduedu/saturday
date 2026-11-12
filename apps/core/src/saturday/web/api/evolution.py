"""Webhook da Evolution API (decisão 0009).

A Evolution não assina o corpo: ela chama pela rede interna do compose, sem
domínio público, com um token longo no header (`x-webhook-token`, configurado
em `webhook.headers` da instância), comparado em tempo constante.

Como o webhook da Meta: grava, responde 200 e deixa o worker processar. A
deduplicação usa o id da mensagem (`key.id`), no status o id com a situação e,
na conexão, o hash do corpo.
"""

from __future__ import annotations

import hmac
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session, sessionmaker

from saturday.canais.evolution import webhook as parser
from saturday.dados.eventos import enfileirar
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.settings import Settings
from saturday.web.api.granatech import evento_id, token_recebido
from saturday.web.api.whatsapp import para_dict
from saturday.web.dependencies import get_fabrica, get_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["evolution"])

ORIGEM = "evolution"


@router.post("/webhooks/evolution", status_code=200)
async def receber(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    fabrica: Annotated[sessionmaker[Session] | None, Depends(get_fabrica)],
) -> Response:
    """Grava os eventos e responde 200. Nunca roda turno aqui."""

    if not settings.evolution_ativo:
        raise HTTPException(status_code=404, detail="canal desligado")
    esperado = settings.evolution_webhook_token.get_secret_value()
    if not esperado:
        # Token vazio nunca vale como senha.
        raise HTTPException(status_code=503, detail="webhook não configurado")
    if not hmac.compare_digest(token_recebido(request).encode(), esperado.encode()):
        logger.warning("evolution_token_invalido")
        raise HTTPException(status_code=401, detail="token inválido")

    try:
        payload = json.loads(await request.body())
    except ValueError:
        raise HTTPException(status_code=400, detail="corpo inválido") from None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="corpo inválido")

    # Toda instância da Evolution do Saturday é atendida (decisão 0010): o token
    # já prova que o evento veio dela.
    linhas = [(evento.evento_id, para_dict(evento)) for evento in parser.eventos(payload)]
    conexao = parser.conexao(payload)
    if conexao is not None:
        # Sem id no evento de conexão: o hash do JSON separa reenvio de evento novo.
        linhas.append((evento_id(payload), conexao))

    if fabrica is not None and linhas:
        with abrir_sessao(fabrica) as sessao:
            for identificador, dados in linhas:
                enfileirar(sessao, origem=ORIGEM, evento_id=identificador, payload=dados)

    # 200 mesmo sem evento: a Evolution não deve reenviar por falta de interesse nosso.
    return Response(status_code=200)
