"""Outbox: reentrega com backoff, desistência e dois workers em paralelo."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from saturday.dados import outbox as fila
from saturday.dados import repositorios
from saturday.dados.modelos import Outbox
from saturday.jobs.outbox import drenar
from saturday.settings import Settings

# Data bem no passado: vence qualquer lease e destrava a linha para o próximo lote.
PASSADO = datetime(2000, 1, 1, tzinfo=UTC)


class EntregadorQueFalha:
    """Falha sempre, ou só nas primeiras ``falhar`` chamadas."""

    def __init__(self, falhar: int | None = None) -> None:
        self.chamadas = 0
        self.falhar = falhar

    def entregar(self, linha: Outbox) -> bool:
        self.chamadas += 1
        falhou = self.falhar is None or self.chamadas <= self.falhar
        return not falhou


def _enfileirar(fabrica: sessionmaker[Session], conversa: str) -> int:
    with fabrica() as sessao:
        linha_conversa = repositorios.obter_ou_criar_conversa(sessao, conversa)
        linha = fila.enfileirar(
            sessao,
            conversa_id=linha_conversa.id,
            canal="webhook",
            payload={"conversation_id": conversa, "answer": "oi"},
        )
        sessao.commit()
        return linha.id


def _liberar(fabrica: sessionmaker[Session], linha_id: int) -> None:
    """Vence o lease da linha sem esperar os 60 s reais."""

    with fabrica() as sessao:
        sessao.execute(
            update(Outbox).where(Outbox.id == linha_id).values(proxima_tentativa_em=PASSADO)
        )
        sessao.commit()


def _estado(fabrica: sessionmaker[Session], linha_id: int) -> tuple[Any, ...]:
    with fabrica() as sessao:
        linha = sessao.get(Outbox, linha_id)
        assert linha is not None
        return (
            linha.entregue_em,
            linha.falhou_em,
            linha.tentativas,
            linha.proxima_tentativa_em,
        )


def test_envio_que_falha_e_reentregue(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    linha_id = _enfileirar(fabrica, conversa)
    entregador = EntregadorQueFalha(falhar=1)

    assert drenar(fabrica, entregador, settings) == 1

    entregue_em, falhou_em, tentativas, _ = _estado(fabrica, linha_id)
    # Falhou: continua na fila, com a tentativa contada.
    assert entregue_em is None
    assert falhou_em is None
    assert tentativas == 1

    _liberar(fabrica, linha_id)
    assert drenar(fabrica, entregador, settings) == 1

    entregue_em, falhou_em, tentativas, _ = _estado(fabrica, linha_id)
    assert entregue_em is not None
    assert falhou_em is None
    assert tentativas == 2
    assert entregador.chamadas == 2


def test_backoff_cresce_a_cada_falha(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    linha_id = _enfileirar(fabrica, conversa)
    entregador = EntregadorQueFalha()

    esperas = []
    for _ in range(3):
        drenar(fabrica, entregador, settings)
        _, _, _, proxima = _estado(fabrica, linha_id)
        esperas.append(proxima)
        _liberar(fabrica, linha_id)

    agora = datetime.now(UTC)
    segundos = [(espera - agora).total_seconds() for espera in esperas]
    assert segundos[0] < segundos[1] < segundos[2]


def test_desiste_depois_do_limite_de_tentativas(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    linha_id = _enfileirar(fabrica, conversa)
    entregador = EntregadorQueFalha()

    for _ in range(settings.outbox_max_tentativas):
        drenar(fabrica, entregador, settings)
        _liberar(fabrica, linha_id)

    entregue_em, falhou_em, tentativas, _ = _estado(fabrica, linha_id)
    assert entregue_em is None  # nunca foi entregue
    assert falhou_em is not None  # e o sistema assume que desistiu
    assert tentativas == settings.outbox_max_tentativas


def test_dois_workers_nao_pegam_a_mesma_linha(
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    """`FOR UPDATE SKIP LOCKED`: cada worker reserva um conjunto disjunto."""

    _enfileirar(fabrica, conversa + "-a")
    _enfileirar(fabrica, conversa + "-b")

    # Os dois pedem uma linha cada, com as transações abertas ao mesmo tempo.
    # Sem SKIP LOCKED, o segundo ficaria bloqueado esperando o primeiro
    # commitar; com SKIP LOCKED, ele leva a outra linha e segue.
    with fabrica() as um, fabrica() as dois:
        primeira = fila.reivindicar(um, 1)
        segunda = fila.reivindicar(dois, 1)
        um.commit()
        dois.commit()

    assert len(primeira) == 1
    assert len(segunda) == 1
    assert primeira[0].id != segunda[0].id

    with fabrica() as sessao:
        pendentes = sessao.scalars(select(Outbox).where(Outbox.entregue_em.is_(None))).all()
    assert len(pendentes) == 2


def test_conversa_sem_envio_nao_drena_nada(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    with fabrica() as sessao:
        repositorios.obter_ou_criar_conversa(sessao, conversa)
        sessao.commit()

    assert drenar(fabrica, EntregadorQueFalha(), settings) == 0
