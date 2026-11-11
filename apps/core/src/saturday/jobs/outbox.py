"""Consumo do outbox: o único dono do reagendamento.

O canal classifica (`Resultado`) e para. Aqui ficam a espera, o teto de
tentativas e a conversão para modelo quando a janela fechou do lado da Meta.

Backoff exponencial com jitter: `base × 2^(n−1) × U(0,5; 1,5)`, teto de 300 s.
O jitter existe para dois workers não baterem na Meta no mesmo instante depois
de uma queda.
"""

from __future__ import annotations

import logging
import random
from typing import Protocol

import httpx
from sqlalchemy.orm import Session, sessionmaker

from saturday.canais.base import Resultado
from saturday.dados import outbox as fila
from saturday.dados.modelos import Outbox
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.services.webhook import WebhookClient
from saturday.settings import Settings

logger = logging.getLogger(__name__)

# Teto do backoff: um envio preso não pode esperar horas para ser tentado.
ESPERA_MAXIMA_S = 300.0
# Fração do jitter em torno da espera calculada.
JITTER = 0.5
# Timeout de leitura pode ter chegado: uma nova tentativa, nunca duas.
MAX_TENTATIVAS_INCERTO = 2


class Entregador(Protocol):
    def entregar(self, linha: Outbox, *, permitir_modelo: bool = False) -> Resultado: ...


class EntregadorWebhook:
    """Entrega pelo webhook configurado.

    O webhook não distingue temporário de permanente: qualquer falha vale nova
    tentativa, como antes da mudança de política do canal WhatsApp.
    """

    def __init__(self, http: httpx.Client, settings: Settings) -> None:
        self._webhook = WebhookClient(http, settings)

    def entregar(self, linha: Outbox, *, permitir_modelo: bool = False) -> Resultado:
        if self._webhook.enviar(linha.payload):
            return Resultado.OK
        return Resultado.TEMPORARIO


class EntregadorPorCanal:
    """Despacha pelo `canal` da linha do outbox."""

    def __init__(self, entregadores: dict[str, Entregador]) -> None:
        self._entregadores = entregadores

    def entregar(self, linha: Outbox, *, permitir_modelo: bool = False) -> Resultado:
        entregador = self._entregadores.get(linha.canal)
        if entregador is None:
            raise ValueError(f"canal sem entregador: {linha.canal}")
        return entregador.entregar(linha, permitir_modelo=permitir_modelo)


def _espera(tentativas: int, base: float) -> float:
    exponencial = base * (2 ** max(tentativas - 1, 0))
    sorteio = float(random.uniform(1 - JITTER, 1 + JITTER))  # noqa: S311 - jitter
    espera = exponencial * sorteio
    return espera if espera < ESPERA_MAXIMA_S else ESPERA_MAXIMA_S


def _entregar(entregador: Entregador, linha: Outbox) -> tuple[Resultado, str]:
    """Tenta entregar; na janela fechada, converte para modelo uma vez."""

    try:
        resultado = entregador.entregar(linha)
    except Exception as exc:  # noqa: BLE001 - o erro vai para a linha, não derruba o lote
        return Resultado.TEMPORARIO, f"{type(exc).__name__}: {exc}"

    if resultado is not Resultado.JANELA_FECHADA:
        return resultado, ""

    logger.info("outbox_converte_para_modelo id=%s", linha.id)
    try:
        return entregador.entregar(linha, permitir_modelo=True), ""
    except Exception as exc:  # noqa: BLE001
        return Resultado.TEMPORARIO, f"modelo: {type(exc).__name__}: {exc}"


def _aplicar(
    sessao: Session,
    linha: Outbox,
    resultado: Resultado,
    erro: str,
    settings: Settings,
) -> None:
    if resultado is Resultado.OK:
        fila.marcar_entregue(sessao, linha)
        logger.info("outbox_entregue id=%s canal=%s", linha.id, linha.canal)
        return

    if resultado is Resultado.PERMANENTE:
        fila.marcar_desistencia(sessao, linha, erro=f"permanente: {erro}")
        logger.error(
            "outbox_desistiu id=%s canal=%s motivo=permanente erro=%s",
            linha.id,
            linha.canal,
            erro,
        )
        return

    limite = (
        MAX_TENTATIVAS_INCERTO
        if resultado is Resultado.TEMPORARIO_INCERTO
        else settings.outbox_max_tentativas
    )

    if linha.tentativas >= limite:
        fila.marcar_desistencia(sessao, linha, erro=f"{resultado}: {erro}")
        logger.error(
            "outbox_desistiu id=%s canal=%s motivo=%s tentativas=%s erro=%s",
            linha.id,
            linha.canal,
            resultado,
            linha.tentativas,
            erro,
        )
        return

    espera = _espera(linha.tentativas, settings.outbox_backoff_base_s)
    fila.marcar_falha(sessao, linha, erro=f"{resultado}: {erro}", espera_s=espera)
    logger.warning(
        "outbox_falhou id=%s canal=%s resultado=%s tentativas=%s espera_s=%.1f erro=%s",
        linha.id,
        linha.canal,
        resultado,
        linha.tentativas,
        espera,
        erro,
    )


def drenar(
    fabrica: sessionmaker[Session],
    entregador: Entregador,
    settings: Settings,
) -> int:
    """Reivindica um lote, entrega e grava o resultado. Devolve quantos tentou.

    A entrega acontece **fora** da transação: segurar a linha travada durante
    uma chamada de rede seria pior do que o problema que a trava resolve.
    """

    with abrir_sessao(fabrica) as reserva:
        linhas = fila.reivindicar(reserva, settings.outbox_lote)

    if not linhas:
        return 0

    for linha in linhas:
        resultado, erro = _entregar(entregador, linha)
        with abrir_sessao(fabrica) as sessao:
            atual = sessao.get(Outbox, linha.id)
            if atual is None:
                continue
            _aplicar(sessao, atual, resultado, erro, settings)

    return len(linhas)
