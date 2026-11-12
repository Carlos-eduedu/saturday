"""Entrega da resposta pela Evolution API.

Sem janela de 24 h e sem modelos (decisão 0009): toda saída é texto livre,
dividido em partes como no WhatsApp da Meta. O canal só classifica; reagendar é
do outbox. O aviso de janela fechada (`modelo_aviso`) não se aplica e é ignorado.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.clt.mensagens import texto as mensagem
from saturday.canais.base import Resultado
from saturday.canais.evolution.cliente import EvolutionClient
from saturday.canais.whatsapp.cliente import ErroIncerto, ErroPermanente, ErroTemporario
from saturday.canais.whatsapp.partes import enviar_em_partes
from saturday.dados.modelos import Outbox

logger = logging.getLogger(__name__)

# Turno que só pede modelo (recontato de marketing): aqui sai como texto.
TEXTO_DO_MODELO = {"recontato_tempo_casa": "recontato_tempo_casa_texto"}


class SaidaEvolution:
    def __init__(self, cliente: EvolutionClient, fabrica: sessionmaker[Session]) -> None:
        self._cliente = cliente
        self._fabrica = fabrica

    def entregar(self, linha: Outbox, *, permitir_modelo: bool = False) -> Resultado:
        """Uma tentativa; ``permitir_modelo`` não se aplica (sem janela)."""

        payload = linha.payload or {}
        numero = str(payload.get("numero") or "")
        instancia = str(payload.get("phone_number_id") or "")
        if not numero or not instancia:
            logger.error("evolution_saida_sem_destino outbox=%s", linha.id)
            return Resultado.PERMANENTE

        texto = str(payload.get("answer") or "")
        modelo = str(payload.get("modelo") or "")
        if modelo:
            chave = TEXTO_DO_MODELO.get(modelo)
            if chave is None:
                logger.error("evolution_modelo_sem_texto outbox=%s modelo=%s", linha.id, modelo)
                return Resultado.PERMANENTE
            texto = mensagem(chave)
        if not texto:
            logger.info("evolution_saida_vazia outbox=%s", linha.id)
            return Resultado.OK

        try:
            enviar_em_partes(
                self._fabrica,
                linha,
                texto,
                lambda parte: self._cliente.enviar_texto(instancia, numero, parte),
            )
        except ErroIncerto as exc:
            logger.warning("evolution_envio_incerto outbox=%s erro=%s", linha.id, exc)
            return Resultado.TEMPORARIO_INCERTO
        except ErroPermanente as exc:
            logger.error("evolution_envio_permanente outbox=%s erro=%s", linha.id, exc)
            return Resultado.PERMANENTE
        except ErroTemporario as exc:
            logger.warning("evolution_envio_temporario outbox=%s erro=%s", linha.id, exc)
            return Resultado.TEMPORARIO
        return Resultado.OK
