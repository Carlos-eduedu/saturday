"""Entrada do worker: eventos de entrada e outbox de saída.

Dois laços, um processo. O primeiro tira eventos do banco e roda o turno; o
segundo entrega o que a API enfileirou. Um envio que falha volta para a fila com
backoff, sem bloquear a resposta ao cliente.
"""

from __future__ import annotations

import logging
import signal
import threading
import time

import httpx

from saturday.dados.sessao import criar_engine, criar_factory
from saturday.health import registrar_batimento
from saturday.jobs import alertas, recontatos
from saturday.jobs.eventos import processar
from saturday.jobs.homologacao import Rodadas
from saturday.jobs.outbox import Entregador, EntregadorPorCanal, EntregadorWebhook, drenar
from saturday.log import configurar_logging
from saturday.settings import Settings, get_settings
from saturday.storage.base import criar_storage
from saturday.web.composicao import (
    criar_canal_evolution,
    criar_canal_whatsapp,
    criar_checkpointer,
    criar_cliente_granatech,
    criar_servico,
)

logger = logging.getLogger(__name__)

# Sem trabalho pendente, quanto esperar antes de olhar as filas de novo.
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
    storage = criar_storage(settings)
    checkpointer, pool = criar_checkpointer(settings)

    with httpx.Client(timeout=httpx.Timeout(30.0)) as http:
        servico = criar_servico(
            http=http,
            settings=settings,
            checkpointer=checkpointer,
            fabrica=fabrica,
            storage=storage,
        )
        entrada_whatsapp, saida_whatsapp = criar_canal_whatsapp(http, settings, fabrica, storage)
        granatech = criar_cliente_granatech(http, settings, fabrica)
        entregadores: dict[str, Entregador] = {
            "webhook": EntregadorWebhook(http, settings),
            "whatsapp": saida_whatsapp,
        }
        evolution = criar_canal_evolution(http, settings, fabrica, storage)
        if evolution is not None:
            entregadores["evolution"] = evolution.saida
        entregador = EntregadorPorCanal(entregadores)
        rodadas = Rodadas(fabrica, settings, parar)

        logger.info("worker_iniciado")
        proxima_verificacao = 0.0
        while not parar.is_set():
            # O healthcheck do container lê este batimento: worker travado
            # não pode continuar parecendo saudável.
            registrar_batimento()
            try:
                eventos = processar(
                    fabrica,
                    servico,
                    entrada_whatsapp,
                    settings,
                    granatech,
                    evolution.entrada if evolution else None,
                    evolution.cliente if evolution else None,
                )
                entregues = drenar(fabrica, entregador, settings)
                rodadas.verificar()
                if time.monotonic() >= proxima_verificacao:
                    alertas.verificar(fabrica, servico)
                    recontatos.disparar(fabrica, servico)
                    proxima_verificacao = time.monotonic() + alertas.INTERVALO_S
            except Exception:
                logger.exception("worker_erro_no_lote")
                parar.wait(INTERVALO_OCIOSO_S)
                continue
            if not eventos and not entregues:
                parar.wait(INTERVALO_OCIOSO_S)

    if pool is not None:
        pool.close()
    engine.dispose()
    logger.info("worker_parado")


def main() -> None:
    settings = get_settings()
    configurar_logging(settings.log_level)
    settings.validar_para_subir()

    parar = threading.Event()
    _parar_em(parar)
    rodar(settings, parar)
