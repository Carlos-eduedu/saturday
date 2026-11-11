"""Recontatos vencidos, disparados pelo worker.

Só o de cota esgotada dispara nesta fase: o turno de sistema tenta a consulta de
novo. O de tempo de casa fica gravado até a Fase 6, que traz o modelo
`recontato_tempo_casa` e o opt-in.

O recontato é marcado como feito antes do turno (no máximo uma vez): se o turno
falhar, fica o log, e não um cliente recebendo a mesma mensagem duas vezes.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.service import AgentService
from saturday.dados import recontatos
from saturday.dados.modelos import Conversa
from saturday.dados.sessao import sessao as abrir_sessao

logger = logging.getLogger(__name__)

LOTE = 20


def disparar(
    fabrica: sessionmaker[Session],
    servico: AgentService,
    agora: datetime | None = None,
) -> int:
    """Roda o turno de sistema dos recontatos vencidos; devolve quantos."""

    agora = agora or datetime.now(UTC)
    with abrir_sessao(fabrica) as sessao:
        alvos = []
        for recontato in recontatos.vencidos(
            sessao, motivo=recontatos.COTA_ESGOTADA, agora=agora, limite=LOTE
        ):
            recontato.feito_em = agora
            conversation_id = sessao.scalar(
                select(Conversa.conversation_id).where(Conversa.id == recontato.conversa_id)
            )
            if conversation_id:
                alvos.append((conversation_id, recontato.tentativas))
    for conversation_id, tentativas in alvos:
        try:
            servico.continuar(conversation_id, f"recontato:{tentativas}")
        except Exception:  # noqa: BLE001 - um recontato não derruba os outros
            logger.exception("recontato_falhou tentativas=%s", tentativas)
    return len(alvos)
