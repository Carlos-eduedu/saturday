"""Entrega da resposta pelo WhatsApp.

O canal **só classifica** o que aconteceu e para. Quem espera e decide desistir é
o outbox (`jobs/outbox.py`): um único dono do reagendamento. Aqui ficam a janela
de 24 h, a divisão em partes e o aviso por modelo quando a janela está fechada.

Fora da janela sai um modelo, nunca o texto: o do aviso que o turno escolheu
(`modelo_aviso`, com o código do link curto quando o modelo tem botão) ou
`atualizacao_pedido`. O texto da resposta não cabe num parâmetro (a Meta recusa
quebra de linha) e fica na linha do outbox até o cliente escrever de novo.
"""

from __future__ import annotations

import logging
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
from saturday.canais.whatsapp.modelos import MODELOS, Modelo
from saturday.canais.whatsapp.partes import enviar_em_partes
from saturday.dados import outbox as fila
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
        if not numero or not phone_number_id:
            logger.error("whatsapp_saida_sem_destino outbox=%s", linha.id)
            return Resultado.PERMANENTE
        modelo = MODELOS.get(str(payload.get("modelo") or ""))
        if modelo is None and not texto:
            logger.info("whatsapp_saida_vazia outbox=%s", linha.id)
            return Resultado.OK

        aberta = self._janela_aberta(str(payload.get("conversation_id") or ""))

        try:
            if modelo is not None:
                # Modelo escolhido no painel: sai como modelo com a janela
                # aberta ou fechada, e nunca espera o cliente.
                self._enviar_modelo_do_painel(linha, numero, phone_number_id, modelo)
            elif permitir_modelo or not aberta:
                self._avisar_por_modelo(linha, numero, phone_number_id)
                return Resultado.AGUARDANDO_CLIENTE
            self._enviar_texto(linha, numero, phone_number_id, texto)
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
        linha: Outbox,
        numero: str,
        phone_number_id: str,
        texto: str,
    ) -> None:
        enviar_em_partes(
            self._fabrica,
            linha,
            texto,
            lambda parte: self._cliente.enviar_texto(phone_number_id, numero, parte),
        )

    def _enviar_modelo_do_painel(
        self,
        linha: Outbox,
        numero: str,
        phone_number_id: str,
        modelo: Modelo,
    ) -> None:
        wamid = self._cliente.enviar_modelo(phone_number_id, numero, modelo)
        mensagem_id = (linha.payload or {}).get("mensagem_id")
        if isinstance(mensagem_id, int):
            with abrir_sessao(self._fabrica) as sessao:
                repositorios.marcar_envio(sessao, mensagem_id, wamid=wamid, status="sent")

    def _avisar_por_modelo(self, linha: Outbox, numero: str, phone_number_id: str) -> None:
        """Um aviso por conversa: o segundo envio pendente espera o mesmo."""

        with abrir_sessao(self._fabrica) as sessao:
            if fila.outro_esperando_cliente(sessao, linha):
                return
        payload = linha.payload or {}
        modelo = MODELOS.get(str(payload.get("modelo_aviso") or "")) or MODELOS[MODELO_PADRAO]
        sufixo = str(payload.get("link_aviso") or "") if modelo.tem_link else ""
        if modelo.tem_link and not sufixo:
            # Modelo de link sem o código não fecha: avisa pelo genérico.
            modelo = MODELOS[MODELO_PADRAO]
        self._cliente.enviar_modelo(phone_number_id, numero, modelo, sufixo_link=sufixo or None)
