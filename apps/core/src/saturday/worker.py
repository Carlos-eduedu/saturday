"""Entrada do worker: drena o outbox até receber sinal para parar.

Roda como processo separado da API: a API grava o envio na transação do turno e
o worker é quem fala com o canal. Um envio que falha volta para a fila com
backoff, sem bloquear a resposta ao cliente.
"""

from __future__ import annotations

import logging
import signal
import threading
import time

import httpx

from saturday.dados.sessao import criar_engine, criar_factory
from saturday.jobs.outbox import EntregadorWebhook, drenar
from saturday.log import configurar_logging
from saturday.settings import Settings, get_settings

logger = logging.getLogger(__name__)

# Sem trabalho pendente, quanto esperar antes de olhar a fila de novo.
INTERVALO_OCIOSO_S = 1.0


def _parar_em(parar: threading.Event) -> None:
    def ao_sinal(sinal: int, _quadro: object) -> None:
        logger.info("worker_encerrando sinal=%s", sinal)
        parar.set()

    signal.signal(signal.SIGTERM, ao_sinal)
    signal.signal(signal.SIGINT, ao_sinal)


def rodar(settings: Settings, parar: threading.Event) -> None:
    engine = criar_engine(settings)
    fabrica = criar_factory(engine)
    with httpx.Client(timeout=httpx.Timeout(30.0)) as http:
        entregador = EntregadorWebhook(http, settings)
        logger.info("worker_iniciado")
        while not parar.is_set():
            try:
                tentados = drenar(fabrica, entregador, settings)
            except Exception:
                logger.exception("worker_erro_no_lote")
                time.sleep(INTERVALO_OCIOSO_S)
                continue
            if tentados == 0:
                parar.wait(INTERVALO_OCIOSO_S)
    engine.dispose()
    logger.info("worker_parado")


def main() -> None:
    settings = get_settings()
    configurar_logging(settings.log_level)
    settings.validar_para_subir()

    parar = threading.Event()
    _parar_em(parar)
    rodar(settings, parar)
