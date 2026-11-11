"""Recontatos vencidos, disparados pelo worker.

- cota esgotada: o turno de sistema tenta a consulta de novo;
- tempo de casa: só gravado com opt-in; o turno de sistema envia o modelo de
  marketing `recontato_tempo_casa` e a jornada recomeça pela triagem. O nó
  confere o opt-in de novo (o cliente pode ter pedido para não receber).

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
        for motivo in (recontatos.COTA_ESGOTADA, recontatos.TEMPO_CASA):
            for recontato in recontatos.vencidos(sessao, motivo=motivo, agora=agora, limite=LOTE):
                recontato.feito_em = agora
                conversation_id = sessao.scalar(
                    select(Conversa.conversation_id).where(Conversa.id == recontato.conversa_id)
                )
                if not conversation_id:
                    continue
                evento = (
                    f"recontato:{recontato.tentativas}"
                    if motivo == recontatos.COTA_ESGOTADA
                    else "recontato_tempo_casa"
                )
                alvos.append((conversation_id, evento))
    for conversation_id, evento in alvos:
        try:
            servico.continuar(conversation_id, evento)
        except Exception:  # noqa: BLE001 - um recontato não derruba os outros
            logger.exception("recontato_falhou evento=%s", evento)
    return len(alvos)
