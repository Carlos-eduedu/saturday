"""Outbox: o único dono do reagendamento.

O canal só devolve `Resultado`; aqui se prova a espera, o teto de tentativas, a
conversão para modelo e o limite de uma nova tentativa no caso incerto.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from saturday.canais.base import Resultado
from saturday.dados import outbox as fila
from saturday.dados import repositorios
from saturday.dados.modelos import Outbox
from saturday.jobs.outbox import ESPERA_MAXIMA_S, JITTER, drenar
from saturday.settings import Settings

# Data no passado: vence o lease e destrava a linha para o próximo lote.
PASSADO = datetime(2000, 1, 1, tzinfo=UTC)


class EntregadorFalso:
    """Devolve os resultados na ordem, registrando se pediram modelo."""

    def __init__(self, resultados: list[Resultado] | None = None) -> None:
        self.resultados = list(resultados or [])
        self.chamadas: list[bool] = []

    def entregar(self, linha: Outbox, *, permitir_modelo: bool = False) -> Resultado:
        self.chamadas.append(permitir_modelo)
        if not self.resultados:
            return Resultado.TEMPORARIO
        return self.resultados.pop(0)


def _enfileirar(fabrica: sessionmaker[Session], conversa: str) -> int:
    with fabrica() as sessao:
        linha_conversa = repositorios.obter_ou_criar_conversa(sessao, conversa)
        linha = fila.enfileirar(
            sessao,
            conversa_id=linha_conversa.id,
            canal="whatsapp",
            payload={"conversation_id": conversa, "answer": "oi"},
        )
        sessao.commit()
        return linha.id


def _liberar(fabrica: sessionmaker[Session], linha_id: int) -> None:
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


def test_ok_marca_entregue(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    linha_id = _enfileirar(fabrica, conversa)

    assert drenar(fabrica, EntregadorFalso([Resultado.OK]), settings) == 1

    entregue_em, falhou_em, tentativas, _ = _estado(fabrica, linha_id)
    assert entregue_em is not None
    assert falhou_em is None
    assert tentativas == 1


def test_temporario_volta_para_a_fila(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    linha_id = _enfileirar(fabrica, conversa)

    drenar(fabrica, EntregadorFalso([Resultado.TEMPORARIO]), settings)

    entregue_em, falhou_em, tentativas, proxima = _estado(fabrica, linha_id)
    assert entregue_em is None
    assert falhou_em is None
    assert tentativas == 1
    assert proxima > datetime.now(UTC)


def test_backoff_cresce_com_jitter_dentro_da_faixa(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    """Base 2 s: 1ª espera em [1;3], 2ª em [2;6], 3ª em [4;12]."""

    linha_id = _enfileirar(fabrica, conversa)
    entregador = EntregadorFalso()

    esperas: list[float] = []
    for _ in range(3):
        drenar(fabrica, entregador, settings)
        _, _, _, proxima = _estado(fabrica, linha_id)
        esperas.append((proxima - datetime.now(UTC)).total_seconds())
        _liberar(fabrica, linha_id)

    base = settings.outbox_backoff_base_s
    for numero, espera in enumerate(esperas, start=1):
        exponencial = base * 2 ** (numero - 1)
        assert exponencial * (1 - JITTER) - 1 <= espera <= exponencial * (1 + JITTER) + 1


def test_permanente_desiste_na_primeira(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    linha_id = _enfileirar(fabrica, conversa)

    drenar(fabrica, EntregadorFalso([Resultado.PERMANENTE]), settings)

    entregue_em, falhou_em, tentativas, _ = _estado(fabrica, linha_id)
    assert entregue_em is None
    assert falhou_em is not None
    assert tentativas == 1


def test_incerto_tenta_no_maximo_uma_vez_a_mais(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    linha_id = _enfileirar(fabrica, conversa)
    entregador = EntregadorFalso([Resultado.TEMPORARIO_INCERTO, Resultado.TEMPORARIO_INCERTO])

    drenar(fabrica, entregador, settings)
    _, falhou_em, tentativas, _ = _estado(fabrica, linha_id)
    assert falhou_em is None  # ainda vale uma tentativa
    assert tentativas == 1

    _liberar(fabrica, linha_id)
    drenar(fabrica, entregador, settings)

    _, falhou_em, tentativas, _ = _estado(fabrica, linha_id)
    assert falhou_em is not None  # a segunda incerteza encerra
    assert tentativas == 2


def test_janela_fechada_converte_para_modelo(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    linha_id = _enfileirar(fabrica, conversa)
    entregador = EntregadorFalso([Resultado.JANELA_FECHADA, Resultado.OK])

    drenar(fabrica, entregador, settings)

    assert entregador.chamadas == [False, True]
    # A conversão acontece na mesma tentativa: não consome o orçamento.
    entregue_em, falhou_em, tentativas, _ = _estado(fabrica, linha_id)
    assert entregue_em is not None
    assert falhou_em is None
    assert tentativas == 1


def test_desiste_depois_do_limite_de_tentativas(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    linha_id = _enfileirar(fabrica, conversa)
    entregador = EntregadorFalso()

    for _ in range(settings.outbox_max_tentativas):
        drenar(fabrica, entregador, settings)
        _liberar(fabrica, linha_id)

    entregue_em, falhou_em, tentativas, _ = _estado(fabrica, linha_id)
    assert entregue_em is None
    assert falhou_em is not None
    assert tentativas == settings.outbox_max_tentativas
    assert settings.outbox_max_tentativas == 6


def test_espera_nunca_passa_do_teto(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    linha_id = _enfileirar(fabrica, conversa)
    entregador = EntregadorFalso()

    for _ in range(5):
        drenar(fabrica, entregador, settings)
        _liberar(fabrica, linha_id)

    _, _, _, proxima = _estado(fabrica, linha_id)
    espera = (proxima - datetime.now(UTC)).total_seconds()
    assert espera <= ESPERA_MAXIMA_S + 1


def test_dois_workers_nao_pegam_a_mesma_linha(
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    """`FOR UPDATE SKIP LOCKED`: cada worker reserva um conjunto disjunto."""

    _enfileirar(fabrica, conversa + "-a")
    _enfileirar(fabrica, conversa + "-b")

    with fabrica() as um, fabrica() as dois:
        primeira = fila.reivindicar(um, 1)
        segunda = fila.reivindicar(dois, 1)
        um.commit()
        dois.commit()

    assert len(primeira) == 1
    assert len(segunda) == 1
    assert primeira[0].id != segunda[0].id


def test_conversa_sem_envio_nao_drena_nada(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    with fabrica() as sessao:
        repositorios.obter_ou_criar_conversa(sessao, conversa)
        sessao.commit()

    assert drenar(fabrica, EntregadorFalso(), settings) == 0


def test_linhas_pendentes_continuam_visiveis(
    settings: Settings,
    fabrica: sessionmaker[Session],
    conversa: str,
) -> None:
    _enfileirar(fabrica, conversa)
    drenar(fabrica, EntregadorFalso([Resultado.TEMPORARIO]), settings)

    with fabrica() as sessao:
        pendentes = sessao.scalars(select(Outbox).where(Outbox.entregue_em.is_(None))).all()
    assert len(pendentes) == 1
