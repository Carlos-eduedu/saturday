"""Tempo real do painel: `LISTEN painel` no Postgres repassado por SSE.

Quem grava (API ou worker) chama `pg_notify` na própria transação
(`dados/repositorios.notificar`); o Postgres só entrega no commit. Cada processo
da API mantém uma conexão `LISTEN` e reparte o aviso entre os navegadores
conectados. O aviso leva só tipo e IDs: o front busca o resto pela API.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

import psycopg

from saturday.dados.repositorios import CANAL_PAINEL

logger = logging.getLogger(__name__)

ESPERA_RECONEXAO_S = 2.0
KEEPALIVE_S = 15.0
FILA_POR_CLIENTE = 100


class Difusor:
    def __init__(self, conninfo: str) -> None:
        self._conninfo = conninfo
        self._clientes: set[asyncio.Queue[str]] = set()
        self._tarefa: asyncio.Task[None] | None = None

    def iniciar(self) -> None:
        self._tarefa = asyncio.create_task(self._escutar())

    async def parar(self) -> None:
        if self._tarefa is not None:
            self._tarefa.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._tarefa

    def assinar(self) -> asyncio.Queue[str]:
        fila: asyncio.Queue[str] = asyncio.Queue(maxsize=FILA_POR_CLIENTE)
        self._clientes.add(fila)
        return fila

    def cancelar(self, fila: asyncio.Queue[str]) -> None:
        self._clientes.discard(fila)

    def publicar(self, carga: str) -> None:
        for fila in list(self._clientes):
            # Cliente lento perde avisos; ao reconectar, o front recarrega tudo.
            with contextlib.suppress(asyncio.QueueFull):
                fila.put_nowait(carga)

    async def _escutar(self) -> None:
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(
                    self._conninfo, autocommit=True
                ) as conexao:
                    await conexao.execute(f"LISTEN {CANAL_PAINEL}")
                    logger.info("painel_escutando")
                    async for aviso in conexao.notifies():
                        self.publicar(aviso.payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("painel_listen_caiu")
                await asyncio.sleep(ESPERA_RECONEXAO_S)


async def fluxo_sse(
    fila: asyncio.Queue[str], keepalive_s: float = KEEPALIVE_S
) -> AsyncIterator[str]:
    """Eventos no formato SSE, com comentário de keepalive para o proxy não cortar."""

    while True:
        try:
            carga = await asyncio.wait_for(fila.get(), timeout=keepalive_s)
        except TimeoutError:
            yield ": keepalive\n\n"
            continue
        yield f"data: {carga}\n\n"
