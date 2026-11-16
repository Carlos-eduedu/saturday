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
            logger.warning("icred_consulta_desconhecida")
            return None
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
        # Repetido não faz mal: o nó ignora o evento fora da etapa `consultando`.
        servico.continuar(conversation_id, EVENTO_RESULTADO)


def desistir(
    fabrica: sessionmaker[Session], payload: dict[str, Any], servico: AgentService
) -> None:
    """A fila desistiu do evento: a conversa que espera o resultado vai para um humano."""

    id_externo = (payload.get("dados") or {}).get("id")
    with abrir_sessao(fabrica) as sessao:
        linha = sessao.scalar(select(ConsultaIcred).where(ConsultaIcred.id_externo == id_externo))
        conversation_id = (
            repositorios.conversation_id_de(sessao, linha.conversa_id) if linha else None
        )
    if conversation_id:
        servico.desistir_de_sistema(conversation_id, EVENTO_RESULTADO)


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
    for id_local, id_externo in vencidas:
        if id_externo is None:  # consulta aberta sempre tem o id do motor
            continue
        try:
            resultado = cliente.ler(id_externo)
        except ErroIcred:
            resultado = None
        if resultado is not None and resultado.final:
            conversation_id = _gravar(fabrica, resultado)
            if conversation_id:
                servico.continuar(conversation_id, EVENTO_RESULTADO)
            continue

        with abrir_sessao(fabrica) as sessao:
            linha = sessao.get(ConsultaIcred, id_local, with_for_update=True)
            # Outro worker (ou o webhook) chegou antes.
            if linha is None or linha.estado not in ABERTAS:
                continue
            linha.estado = DESISTIDA
            repositorios.abrir_alerta(
                sessao,
                "consulta_parada",
                conversa_id=linha.conversa_id,
                detalhe={"banco": "icred", "id": id_externo},
            )
            conversation_id = repositorios.conversation_id_de(sessao, linha.conversa_id)
        abandonadas += 1
        if conversation_id:
            servico.continuar(conversation_id, EVENTO_PRAZO)
    return abandonadas
