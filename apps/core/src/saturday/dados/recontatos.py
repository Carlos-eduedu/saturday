"""Recontatos: voltar a falar com o cliente numa data marcada."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from saturday.dados.modelos import Recontato

COTA_ESGOTADA = "cota_esgotada"
TEMPO_CASA = "tempo_casa"


def agendar(
    sessao: Session,
    *,
    conversa_id: uuid.UUID,
    motivo: str,
    quando: datetime,
    tentativas: int = 0,
) -> Recontato:
    recontato = Recontato(
        conversa_id=conversa_id, motivo=motivo, quando=quando, tentativas=tentativas
    )
    sessao.add(recontato)
    sessao.flush()
    return recontato


def vencidos(sessao: Session, *, motivo: str, agora: datetime, limite: int) -> list[Recontato]:
    """Recontatos vencidos e não feitos, travados para este worker."""

    return list(
        sessao.scalars(
            select(Recontato)
            .where(
                Recontato.motivo == motivo,
                Recontato.feito_em.is_(None),
                Recontato.quando <= agora,
            )
            .order_by(Recontato.quando)
            .limit(limite)
            .with_for_update(skip_locked=True)
        )
    )


def ultimo(sessao: Session, *, conversa_id: uuid.UUID, motivo: str) -> Recontato | None:
    return sessao.scalars(
        select(Recontato)
        .where(Recontato.conversa_id == conversa_id, Recontato.motivo == motivo)
        .order_by(Recontato.id.desc())
    ).first()
