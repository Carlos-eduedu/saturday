"""Entrega da resposta pelo WhatsApp.

O canal **só classifica** o que aconteceu e para. Quem espera e decide desistir é
o outbox (`jobs/outbox.py`): um único dono do reagendamento. Aqui ficam a janela
de 24 h, a divisão em partes e a conversão para modelo quando a Meta recusa texto.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from saturday.canais.base import Resultado
from saturday.canais.whatsapp.cliente import (
    ErroIncerto,
    ErroJanelaFechada,
    ErroPermanente,
    ErroTemporario,
    WhatsAppClient,
)
from saturday.canais.whatsapp.janela import janela_aberta
from saturday.canais.whatsapp.modelos import MODELOS
from saturday.canais.whatsapp.partes import INTERVALO_ENTRE_PARTES_S, dividir
from saturday.dados import repositorios
from saturday.dados.modelos import Outbox
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.settings import Settings

logger = logging.getLogger(__name__)

MODELO_PADRAO = "atualizacao_pedido"


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

    def entregar(self, linha: Outbox, *, permitir_modelo: bool = False) -> Resultado:
        """Uma tentativa. ``permitir_modelo`` vem do outbox na conversão."""

        payload = linha.payload or {}
        numero = str(payload.get("numero") or "")
        phone_number_id = str(payload.get("phone_number_id") or "")
        texto = str(payload.get("answer") or "")
        mensagem_id = payload.get("mensagem_id")

        if not numero or not phone_number_id:
            logger.error("whatsapp_saida_sem_destino outbox=%s", linha.id)
            return Resultado.PERMANENTE
        if not texto:
            logger.info("whatsapp_saida_vazia outbox=%s", linha.id)
            return Resultado.OK

        aberta = self._janela_aberta(str(payload.get("conversation_id") or ""))

        try:
            if permitir_modelo or not aberta:
                wamid, status = self._enviar_modelo(numero, phone_number_id, texto)
            else:
                wamid, status = self._enviar_texto(numero, phone_number_id, texto)
        except ErroJanelaFechada:
            # Nossa janela dizia aberta, a Meta discordou: o outbox converte.
            return Resultado.JANELA_FECHADA
        except ErroIncerto as exc:
            logger.warning("whatsapp_envio_incerto outbox=%s erro=%s", linha.id, exc)
            return Resultado.TEMPORARIO_INCERTO
        except ErroPermanente as exc:
            logger.error("whatsapp_envio_permanente outbox=%s erro=%s", linha.id, exc)
            return Resultado.PERMANENTE
        except ErroTemporario as exc:
            logger.warning("whatsapp_envio_temporario outbox=%s erro=%s", linha.id, exc)
            return Resultado.TEMPORARIO

        self._registrar(mensagem_id, wamid=wamid, status=status)
        return Resultado.OK

    def _janela_aberta(self, conversation_id: str) -> bool:
        if not conversation_id:
            return False
        with abrir_sessao(self._fabrica) as sessao:
            conversa = repositorios.buscar_conversa(sessao, conversation_id)
            ultima = conversa.ultima_entrada_em if conversa is not None else None
        return janela_aberta(ultima, datetime.now(UTC))

    def _enviar_texto(
        self,
        numero: str,
        phone_number_id: str,
        texto: str,
    ) -> tuple[str | None, str]:
        partes = dividir(texto)
        primeiro: str | None = None
        for indice, parte in enumerate(partes):
            wamid = self._cliente.enviar_texto(phone_number_id, numero, parte)
            primeiro = primeiro or wamid
            if indice < len(partes) - 1:
                time.sleep(INTERVALO_ENTRE_PARTES_S)
        return primeiro, "sent"

    def _enviar_modelo(
        self,
        numero: str,
        phone_number_id: str,
        texto: str,
    ) -> tuple[str | None, str]:
        modelo = MODELOS[MODELO_PADRAO]
        wamid = self._cliente.enviar_modelo(
            phone_number_id,
            numero,
            modelo,
            parametros=[texto],
        )
        return wamid, "sent"

    def _registrar(self, mensagem_id: object, *, wamid: str | None, status: str) -> None:
        if not isinstance(mensagem_id, int):
            return
        with abrir_sessao(self._fabrica) as sessao:
            repositorios.marcar_envio(sessao, mensagem_id, wamid=wamid, status=status)
