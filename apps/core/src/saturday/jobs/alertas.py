"""Alertas que nascem do tempo, verificados pelo worker.

- cliente sem resposta numa conversa assumida;
- consulta da Granatech sem evento há mais de 15 min (o webhook é o único
  aviso de que ela ficou pronta; se ele se perde, alguém precisa saber). Se ela
  ainda espera a autorização do cliente, o termo pela API não pegou: a conversa
  recebe o link do termo como plano B.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.service import AgentService
from saturday.bancos.granatech import status as ordem_granatech
from saturday.dados import repositorios
from saturday.dados.modelos import Alerta, ConsultaGranatech, Conversa, Mensagem
from saturday.dados.sessao import sessao as abrir_sessao

logger = logging.getLogger(__name__)

SEM_RESPOSTA = timedelta(minutes=10)
CONSULTA_PARADA = timedelta(minutes=15)
INTERVALO_S = 60.0
# Só um worker verifica por vez: dois abririam o mesmo alerta.
TRAVA_VERIFICACAO = 0x5A7A_0003


def verificar(fabrica: sessionmaker[Session], servico: AgentService | None = None) -> int:
    """Abre os alertas de tempo; devolve quantos abriu."""

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
        paradas, termo_pendente = _consultas_paradas(sessao)
    if conversas:
        logger.info("alertas_sem_resposta quantidade=%s", len(conversas))
    if servico is not None:
        for conversation_id in termo_pendente:
            servico.continuar(conversation_id, "termo_pendente")
    return len(conversas) + paradas


def _consultas_paradas(sessao: Session) -> tuple[int, list[str]]:
    """Um alerta por consulta não final sem nenhuma mudança há 15 min.

    Devolve também as conversas cuja consulta parou esperando a autorização.
    """

    finais = [
        s for s, posicao in ordem_granatech.CONSULTA.items() if posicao == ordem_granatech.FINAL
    ]
    avisada = exists().where(
        Alerta.tipo == "consulta_parada",
        Alerta.detalhe["consulta"].astext == ConsultaGranatech.id_externo,
    )
    consultas = sessao.scalars(
        select(ConsultaGranatech).where(
            ConsultaGranatech.status.not_in(finais),
            ConsultaGranatech.atualizada_em < func.now() - CONSULTA_PARADA,
            ~avisada,
        )
    ).all()
    for consulta in consultas:
        repositorios.abrir_alerta(
            sessao,
            "consulta_parada",
            conversa_id=consulta.conversa_id,
            detalhe={"consulta": consulta.id_externo, "status": consulta.status},
        )
    if consultas:
        logger.info("alertas_consulta_parada quantidade=%s", len(consultas))
    ids = [
        c.conversa_id
        for c in consultas
        if c.status == "AWAITING_CLIENT_AUTHORIZATION" and c.conversa_id is not None
    ]
    termo_pendente = (
        list(sessao.scalars(select(Conversa.conversation_id).where(Conversa.id.in_(ids))))
        if ids
        else []
    )
    return len(consultas), termo_pendente
