"""Entrega da resposta pelo WhatsApp.

Janela de 24 h aberta, texto livre em partes. Fechada, só modelo aprovado — a
Meta recusa texto com o código 131047. Erro temporário tem a própria escada de
esperas (2 s, 5 s, 10 s); esgotada, a linha volta para o outbox, que é o backstop
durável.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from typing import TypeVar

from sqlalchemy.orm import Session, sessionmaker

from saturday.canais.whatsapp.cliente import ErroPermanente, ErroTemporario, WhatsAppClient
from saturday.canais.whatsapp.janela import janela_aberta
from saturday.canais.whatsapp.modelos import MODELOS
from saturday.canais.whatsapp.partes import INTERVALO_ENTRE_PARTES_S, dividir
from saturday.dados import repositorios
from saturday.dados.modelos import Outbox
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.settings import Settings

logger = logging.getLogger(__name__)

# Escada de espera do canal. Diferente do backoff do outbox de propósito: aqui é
# a tentativa imediata, lá é a reentrega durável.
ESPERAS_S = (2.0, 5.0, 10.0)

MODELO_PADRAO = "atualizacao_pedido"

T = TypeVar("T")


class SaidaWhatsApp:
    def __init__(
        self,
        cliente: WhatsAppClient,
        fabrica: sessionmaker[Session],
        settings: Settings,
    ) -> None:
        self._cliente = cliente
        self._fabrica = fabrica
        self._settings = settings

    def entregar(self, linha: Outbox) -> bool:
        payload = linha.payload or {}
        numero = str(payload.get("numero") or "")
        phone_number_id = str(payload.get("phone_number_id") or "")
        texto = str(payload.get("answer") or "")
        mensagem_id = payload.get("mensagem_id")

        if not numero or not phone_number_id:
            logger.error("whatsapp_saida_sem_destino outbox=%s", linha.id)
            return False
        if not texto:
            logger.info("whatsapp_saida_vazia outbox=%s", linha.id)
            return True

        aberta = self._janela_aberta(str(payload.get("conversation_id") or ""))

        try:
            if aberta:
                wamid, status = self._enviar_texto(numero, phone_number_id, texto)
            else:
                wamid, status = self._enviar_modelo(numero, phone_number_id, texto)
        except ErroPermanente as exc:
            logger.error("whatsapp_envio_permanente outbox=%s erro=%s", linha.id, exc)
            return False
        except ErroTemporario as exc:
            logger.warning("whatsapp_envio_temporario outbox=%s erro=%s", linha.id, exc)
            return False

        self._registrar(mensagem_id, wamid=wamid, status=status)
        return True

    def _janela_aberta(self, conversation_id: str) -> bool:
        if not conversation_id:
            return False
        with abrir_sessao(self._fabrica) as sessao:
            conversa = repositorios.buscar_conversa(sessao, conversation_id)
            ultima = conversa.ultima_entrada_em if conversa is not None else None
        return janela_aberta(ultima, datetime.now(UTC))

    def _com_retry(self, enviar: Callable[[], T]) -> T:
        """Tenta de novo só em erro temporário, com a escada do canal.

        A última tentativa fica fora do laço: se falhar, o erro sobe e o outbox
        decide a reentrega durável.
        """

        for tentativa, espera in enumerate(ESPERAS_S, start=1):
            try:
                return enviar()
            except ErroTemporario:
                logger.info("whatsapp_retry tentativa=%s espera_s=%s", tentativa, espera)
                time.sleep(espera)
        return enviar()

    def _enviar_texto(
        self,
        numero: str,
        phone_number_id: str,
        texto: str,
    ) -> tuple[str | None, str]:
        partes = dividir(texto)
        primeiro: str | None = None
        for indice, parte in enumerate(partes):
            wamid = self._com_retry(
                partial(self._cliente.enviar_texto, phone_number_id, numero, parte)
            )
            primeiro = primeiro or wamid
            if indice < len(partes) - 1:
                time.sleep(INTERVALO_ENTRE_PARTES_S)
        return primeiro, "sent"

    def _enviar_modelo(
        self, numero: str, phone_number_id: str, texto: str
    ) -> tuple[str | None, str]:
        modelo = MODELOS[MODELO_PADRAO]
        wamid = self._com_retry(
            lambda: self._cliente.enviar_modelo(
                phone_number_id,
                numero,
                modelo,
                parametros=[texto],
            )
        )
        return wamid, "sent"

    def _registrar(self, mensagem_id: object, *, wamid: str | None, status: str) -> None:
        if not isinstance(mensagem_id, int):
            return
        with abrir_sessao(self._fabrica) as sessao:
            repositorios.marcar_envio(sessao, mensagem_id, wamid=wamid, status=status)
