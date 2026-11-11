"""Fila de eventos de entrada.

O webhook grava e responde 200; o worker lê, roda o turno e marca. A chave única
`(origem, evento_id)` é o que transforma o reenvio da Meta em no-op.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from saturday.dados.modelos import EventoRecebido

# Lease do evento em processamento: se o worker morrer, outro assume depois.
LEASE = timedelta(seconds=300)


def agora() -> datetime:
    return datetime.now(UTC)


def enfileirar(
    sessao: Session,
    *,
    origem: str,
    evento_id: str,
    payload: dict[str, Any],
) -> bool:
    """Grava o evento. ``False`` quando ele já tinha sido recebido."""

    resultado = sessao.execute(
        insert(EventoRecebido)
        .values(origem=origem, evento_id=evento_id, payload=payload)
        .on_conflict_do_nothing(index_elements=["origem", "evento_id"])
        .returning(EventoRecebido.id)
    )
    return resultado.scalar_one_or_none() is not None


def reivindicar(sessao: Session, limite: int) -> list[EventoRecebido]:
    """Reserva eventos pendentes, sem esperar pelos que outro worker pegou.

    O ``processado_em`` provisório funciona como lease: some no fim do
    processamento ou vence sozinho, e o evento volta para a fila.
    """

    linhas = sessao.scalars(
        select(EventoRecebido)
        .where(
            EventoRecebido.processado_em.is_(None),
            EventoRecebido.falhou_em.is_(None),
        )
        .order_by(EventoRecebido.id)
        .limit(limite)
        .with_for_update(skip_locked=True)
    ).all()

    reserva = agora() + LEASE
    for linha in linhas:
        linha.processado_em = reserva
        linha.tentativas += 1
    sessao.flush()
    return list(linhas)


def marcar_processado(sessao: Session, linha: EventoRecebido) -> None:
    linha.processado_em = agora()
    sessao.flush()


def marcar_falha(
    sessao: Session,
    linha: EventoRecebido,
    *,
    erro: str,
    desistir: bool,
) -> None:
    linha.ultimo_erro = erro[:2000]
    if desistir:
        linha.falhou_em = agora()
        linha.processado_em = None
        return
    # Devolve para a fila: a próxima passada tenta de novo.
    linha.processado_em = None
    sessao.flush()


def pendentes(sessao: Session) -> int:
    return int(
        sessao.scalar(
            select(func.count())
            .select_from(EventoRecebido)
            .where(
                EventoRecebido.processado_em.is_(None),
                EventoRecebido.falhou_em.is_(None),
            )
        )
        or 0
    )
