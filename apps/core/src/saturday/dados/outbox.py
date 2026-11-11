"""Outbox: o envio nasce na transação do turno e é entregue pelo worker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, and_, exists, func, not_, select
from sqlalchemy.orm import Session

from saturday.dados.modelos import Conversa, Outbox

# Tempo que a linha fica reservada por um worker. Se ele morrer no meio da
# entrega, outro worker a pega depois deste prazo — é o lease que evita duas
# entregas simultâneas sem manter transação aberta durante a chamada de rede.
LEASE = timedelta(seconds=60)


def agora() -> datetime:
    return datetime.now(UTC)


def enfileirar(
    sessao: Session,
    *,
    conversa_id: Any,
    canal: str,
    payload: dict[str, Any],
) -> Outbox:
    """Grava o envio na transação corrente. Só é durável no commit do turno."""

    linha = Outbox(conversa_id=conversa_id, canal=canal, payload=payload)
    sessao.add(linha)
    sessao.flush()
    return linha


def _esperando_cliente() -> ColumnElement[bool]:
    """Linha que já mandou o modelo e o cliente ainda não escreveu depois dele."""

    return and_(
        Outbox.aguardando_cliente_desde.is_not(None),
        not_(
            exists().where(
                Conversa.id == Outbox.conversa_id,
                Conversa.ultima_entrada_em > Outbox.aguardando_cliente_desde,
            )
        ),
    )


def reivindicar(sessao: Session, limite: int) -> list[Outbox]:
    """Reserva até ``limite`` envios prontos, sem esperar por linhas travadas.

    ``FOR UPDATE SKIP LOCKED`` é o que permite dois workers rodando ao mesmo
    tempo: cada um pega um conjunto disjunto de linhas em vez de um bloquear o
    outro.
    """

    linhas = sessao.scalars(
        select(Outbox)
        .where(
            Outbox.entregue_em.is_(None),
            Outbox.falhou_em.is_(None),
            Outbox.proxima_tentativa_em <= func.now(),
            not_(_esperando_cliente()),
        )
        .order_by(Outbox.id)
        .limit(limite)
        .with_for_update(skip_locked=True)
    ).all()
    reserva = agora() + LEASE
    for linha in linhas:
        linha.tentativas += 1
        linha.proxima_tentativa_em = reserva
    sessao.flush()
    return list(linhas)


def outro_esperando_cliente(sessao: Session, linha: Outbox) -> bool:
    """Já há aviso por modelo pendente nesta conversa: não manda outro."""

    return bool(
        sessao.scalar(
            select(
                exists().where(
                    Outbox.conversa_id == linha.conversa_id,
                    Outbox.id != linha.id,
                    Outbox.entregue_em.is_(None),
                    Outbox.falhou_em.is_(None),
                    _esperando_cliente(),
                )
            )
        )
    )


def marcar_aguardando_cliente(sessao: Session, linha: Outbox) -> None:
    """O modelo avisou; o texto volta à fila quando o cliente escrever.

    shortcut: o horário é o do registro, não o do envio do modelo; uma mensagem
    do cliente nesse segundo deixa o texto esperando a próxima. Se aparecer no
    painel, grave o horário antes de chamar a Meta.
    """

    linha.aguardando_cliente_desde = func.now()
    # Quem segura a linha agora é a espera, não o lease: quando o cliente
    # escrever, ela sai na hora e antes das respostas mais novas.
    linha.proxima_tentativa_em = func.now()
    # Esperar não é falhar: a entrega do texto começa com as tentativas zeradas.
    linha.tentativas = 0
    linha.ultimo_erro = None
    sessao.flush()


def registrar_partes_enviadas(sessao: Session, linha_id: int, quantidade: int) -> None:
    """Progresso da entrega em partes: a nova tentativa não repete as já enviadas."""

    linha = sessao.get(Outbox, linha_id)
    if linha is None:
        return
    linha.payload = {**linha.payload, "partes_enviadas": quantidade}
    sessao.flush()


def marcar_entregue(sessao: Session, linha: Outbox) -> None:
    linha.entregue_em = agora()
    sessao.flush()


def marcar_desistencia(sessao: Session, linha: Outbox, *, erro: str) -> None:
    """Tentativas esgotadas: para de tentar, sem fingir que entregou."""

    linha.falhou_em = agora()
    linha.ultimo_erro = erro[:2000]
    sessao.flush()


def marcar_falha(sessao: Session, linha: Outbox, *, erro: str, espera_s: float) -> None:
    """Reagenda o envio; ``falhou`` quando as tentativas se esgotaram."""

    linha.ultimo_erro = erro[:2000]
    linha.proxima_tentativa_em = agora() + timedelta(seconds=espera_s)
    sessao.flush()
