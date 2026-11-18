"""Eventos do motor do iCred e o prazo de espera da consulta (decisão 0027).

O webhook `consulta.concluida` grava o resultado e dispara um turno de sistema.
Se ele não chega em ``SATURDAY_ICRED_ESPERA_MIN``, o worker lê a consulta por id;
continuando parada, a conversa segue sem o iCred e a equipe recebe um alerta.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.icred.nos import EVENTO_PRAZO, EVENTO_RESULTADO
from saturday.agent.service import AgentService
from saturday.bancos.icred.cliente import (
    ABERTAS,
    DESISTIDA,
    ClienteIcred,
    ErroIcred,
    gravar_resultado,
)
from saturday.bancos.icred.normalizacao import Resultado, normalizar_consulta
from saturday.dados import repositorios
from saturday.dados.modelos import ConsultaIcred
from saturday.dados.sessao import sessao as abrir_sessao

logger = logging.getLogger(__name__)

CONSULTA_CONCLUIDA = "consulta.concluida"


def _gravar(fabrica: sessionmaker[Session], resultado: Resultado) -> str | None:
    """Grava o resultado; devolve a conversa a avisar se a consulta terminou."""

    with abrir_sessao(fabrica) as sessao:
        gravar_resultado(sessao, resultado)
        linha = sessao.scalar(
            select(ConsultaIcred).where(ConsultaIcred.id_externo == resultado.id_externo)
        )
        if linha is None:
            # O resultado pode chegar antes de `abrir_consulta` gravar o id do
            # motor: falhar faz a fila tentar de novo.
            raise ValueError("consulta do iCred desconhecida")
        if linha.estado == DESISTIDA:
            # A conversa desistiu da consulta (prazo ou extrato de outro titular).
            logger.info("icred_resultado_de_consulta_desistida consulta=%s", linha.id)
        if linha.estado != resultado.estado or not resultado.final:
            return None
        return repositorios.conversation_id_de(sessao, linha.conversa_id)


def aplicar(fabrica: sessionmaker[Session], payload: dict[str, Any], servico: AgentService) -> None:
    """Só `consulta.concluida` interessa na fase 1; o resto é ignorado."""

    if payload.get("evento") != CONSULTA_CONCLUIDA:
        return
    dados = payload.get("dados")
    if not isinstance(dados, dict):
        raise ValueError("evento do iCred sem dados")
    conversation_id = _gravar(fabrica, normalizar_consulta(dados))
    if conversation_id:
        # Repetido não faz mal: o nó ignora o evento que não é da consulta vigente.
        servico.continuar(conversation_id, EVENTO_RESULTADO)


def desistir(
    fabrica: sessionmaker[Session], payload: dict[str, Any], servico: AgentService
) -> None:
    """A fila desistiu do evento: a conversa que espera o resultado vai para um humano."""

    dados = payload.get("dados")
    id_externo = dados.get("id") if isinstance(dados, dict) else None
    # Sem id, a comparação viraria `IS NULL` e pegaria a consulta de outra conversa.
    if not isinstance(id_externo, str):
        return
    with abrir_sessao(fabrica) as sessao:
        linha = sessao.scalar(select(ConsultaIcred).where(ConsultaIcred.id_externo == id_externo))
        conversation_id = (
            repositorios.conversation_id_de(sessao, linha.conversa_id) if linha else None
        )
    if conversation_id:
        servico.desistir_de_sistema(conversation_id, EVENTO_RESULTADO)


def _avisar(servico: AgentService, conversation_id: str, evento: str) -> None:
    """Turno de sistema fora da fila: se falhar, ninguém tenta de novo, então a
    conversa vai para um humano em vez de ficar esperando o resultado."""

    try:
        servico.continuar(conversation_id, evento)
    except Exception:
        logger.exception("icred_turno_falhou evento=%s", evento)
        servico.desistir_de_sistema(conversation_id, evento)


def verificar_prazo(
    fabrica: sessionmaker[Session], cliente: ClienteIcred, servico: AgentService
) -> int:
    """Consultas sem resposta além do prazo; devolve quantas a conversa abandonou."""

    limite = func.now() - timedelta(minutes=cliente.espera_min)
    with abrir_sessao(fabrica) as sessao:
        vencidas = sessao.execute(
            select(ConsultaIcred.id, ConsultaIcred.id_externo).where(
                ConsultaIcred.estado.in_(ABERTAS), ConsultaIcred.criada_em < limite
            )
        ).all()

    abandonadas = 0
    # O laço do worker é um só: com o motor fora do ar, a primeira leitura que
    # falha vale para todas, e as demais não gastam o timeout de novo.
    motor_fora = False
    for id_local, id_externo in vencidas:
        if id_externo is None:  # consulta aberta sempre tem o id do motor
            continue
        resultado = None
        if not motor_fora:
            try:
                resultado = cliente.ler(id_externo)
            except ErroIcred as erro:
                motor_fora = erro.status is None or erro.status >= 500
        if resultado is not None and resultado.final:
            conversation_id = _gravar(fabrica, resultado)
            if conversation_id:
                _avisar(servico, conversation_id, EVENTO_RESULTADO)
            continue

        with abrir_sessao(fabrica) as sessao:
            linha = sessao.get(ConsultaIcred, id_local, with_for_update=True)
            # Outro worker (ou o webhook) chegou antes.
            if linha is None or linha.estado not in ABERTAS:
                continue
            linha.estado = DESISTIDA
            repositorios.abrir_alerta(
                sessao,
                "icred_consulta_parada",
                conversa_id=linha.conversa_id,
                detalhe={"id": id_externo},
            )
            conversation_id = repositorios.conversation_id_de(sessao, linha.conversa_id)
        abandonadas += 1
        if conversation_id:
            _avisar(servico, conversation_id, EVENTO_PRAZO)
    return abandonadas
