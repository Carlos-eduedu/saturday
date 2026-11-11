"""Consumo do outbox: cada envio é tentado fora da transação, com backoff."""

from __future__ import annotations

import logging
from typing import Protocol

import httpx
from sqlalchemy.orm import Session, sessionmaker

from saturday.dados import outbox as fila
from saturday.dados.modelos import Outbox
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.services.webhook import WebhookClient
from saturday.settings import Settings

logger = logging.getLogger(__name__)

# Teto do backoff: um envio preso não pode esperar horas para ser tentado.
ESPERA_MAXIMA_S = 300.0


class Entregador(Protocol):
    def entregar(self, linha: Outbox) -> bool: ...


class EntregadorPorCanal:
    """Despacha pelo `canal` da linha do outbox.

    É o seam para as fases seguintes: acrescentar um canal é acrescentar um
    entregador aqui, sem mexer no laço de consumo.
    """

    def __init__(self, entregadores: dict[str, Entregador]) -> None:
        self._entregadores = entregadores

    def entregar(self, linha: Outbox) -> bool:
        entregador = self._entregadores.get(linha.canal)
        if entregador is None:
            raise ValueError(f"canal sem entregador: {linha.canal}")
        return entregador.entregar(linha)


class EntregadorWebhook:
    """Entrega pelo webhook configurado. Devolve ``False`` quando o canal recusa."""

    def __init__(self, http: httpx.Client, settings: Settings) -> None:
        self._webhook = WebhookClient(http, settings)

    def entregar(self, linha: Outbox) -> bool:
        return self._webhook.enviar(linha.payload)


def _espera(tentativas: int, base: float) -> float:
    fator = float(2 ** max(tentativas - 1, 0))
    espera = base * fator
    return espera if espera < ESPERA_MAXIMA_S else ESPERA_MAXIMA_S


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
        erro = ""
        try:
            entregue = entregador.entregar(linha)
        except Exception as exc:  # noqa: BLE001 - o erro vai para a linha, não derruba o loop
            entregue = False
            erro = f"{type(exc).__name__}: {exc}"
        else:
            if not entregue:
                erro = "canal recusou o envio"

        with abrir_sessao(fabrica) as resultado:
            atual = resultado.get(Outbox, linha.id)
            if atual is None:
                continue
            if entregue:
                fila.marcar_entregue(resultado, atual)
                logger.info("outbox_entregue id=%s canal=%s", atual.id, atual.canal)
            elif atual.tentativas >= settings.outbox_max_tentativas:
                fila.marcar_desistencia(resultado, atual, erro=erro)
                logger.error(
                    "outbox_desistiu id=%s canal=%s tentativas=%s erro=%s",
                    atual.id,
                    atual.canal,
                    atual.tentativas,
                    erro,
                )
            else:
                espera = _espera(atual.tentativas, settings.outbox_backoff_base_s)
                fila.marcar_falha(resultado, atual, erro=erro, espera_s=espera)
                logger.warning(
                    "outbox_falhou id=%s tentativas=%s espera_s=%.1f erro=%s",
                    atual.id,
                    atual.tentativas,
                    espera,
                    erro,
                )

    return len(linhas)
