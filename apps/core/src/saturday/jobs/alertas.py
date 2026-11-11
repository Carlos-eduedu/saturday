"""Alerta de cliente sem resposta numa conversa assumida."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session, sessionmaker

from saturday.dados import repositorios
from saturday.dados.modelos import Alerta, Conversa, Mensagem
from saturday.dados.sessao import sessao as abrir_sessao

logger = logging.getLogger(__name__)

SEM_RESPOSTA = timedelta(minutes=10)
INTERVALO_S = 60.0
# Só um worker verifica por vez: dois abririam o mesmo alerta.
TRAVA_VERIFICACAO = 0x5A7A_0003


def verificar(fabrica: sessionmaker[Session]) -> int:
    """Abre um alerta por mensagem do cliente sem resposta há mais de 10 min."""

    with abrir_sessao(fabrica) as sessao:
        if not sessao.scalar(select(func.pg_try_advisory_xact_lock(TRAVA_VERIFICACAO))):
            return 0
        respondida = exists().where(
            Mensagem.conversa_id == Conversa.id,
            Mensagem.direcao == "saida",
            Mensagem.criada_em > Conversa.ultima_entrada_em,
        )
        avisada = exists().where(
            Alerta.conversa_id == Conversa.id,
            Alerta.tipo == "sem_resposta",
            Alerta.criado_em > Conversa.ultima_entrada_em,
        )
        conversas = sessao.scalars(
            select(Conversa).where(
                and_(
                    Conversa.atendimento == "assumida",
                    Conversa.ultima_entrada_em < func.now() - SEM_RESPOSTA,
                    ~respondida,
                    ~avisada,
                )
            )
        ).all()
        for conversa in conversas:
            repositorios.abrir_alerta(
                sessao,
                "sem_resposta",
                conversa_id=conversa.id,
                detalhe={"atendente_id": str(conversa.atendente_id)},
            )
    if conversas:
        logger.info("alertas_sem_resposta quantidade=%s", len(conversas))
    return len(conversas)
