"""Aplicação dos eventos da Granatech pelo worker.

O evento só atualiza o registro local (consulta ou proposta), na ordem da
jornada: status final nunca é sobrescrito e evento atrasado não faz regredir.
Tudo o que chega fica no histórico, inclusive o que foi ignorado. O que o
cliente recebe por causa de cada status entra nas fases 5 e 6.

Quando uma consulta fica pronta (``SUCCESS``), o detalhe é buscado e gravado.
Se ele ainda vier sem margens, o evento falha e volta para a fila. Com o
detalhe gravado (ou com a consulta encerrada sem ele), a conversa recebe um
turno de sistema para seguir a jornada CLT. O turno é idempotente: a etapa
``consultando`` só avança uma vez.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from saturday.agent.service import AgentService
from saturday.bancos.granatech import status as ordem
from saturday.bancos.granatech.cliente import ClienteGranatech
from saturday.dados import repositorios
from saturday.dados.modelos import ConsultaGranatech, Conversa, PropostaGranatech
from saturday.dados.sessao import sessao as abrir_sessao

logger = logging.getLogger(__name__)

ALERTA = "granatech_evento"


class DetalheAindaNaoPronto(Exception):
    """``SUCCESS`` chegou, mas o detalhe ainda veio sem margens."""


def aplicar(
    fabrica: sessionmaker[Session],
    cliente: ClienteGranatech | None,
    payload: dict[str, Any],
    servico: AgentService | None = None,
) -> None:
    tipo = str(payload.get("tipo") or "").lower()
    if tipo == "consulta":
        _consulta(fabrica, cliente, payload, servico)
    elif tipo == "proposta":
        _proposta(fabrica, payload)
    else:
        with abrir_sessao(fabrica) as sessao:
            _alertar(sessao, None, motivo="tipo_desconhecido", tipo=tipo or None)


def _agora() -> str:
    return datetime.now(UTC).isoformat()


def _alertar(sessao: Session, conversa_id: Any, **detalhe: Any) -> None:
    # Só identificadores e status: o payload traz CPF.
    logger.warning("granatech_evento_alerta %s", detalhe)
    repositorios.abrir_alerta(sessao, ALERTA, conversa_id=conversa_id, detalhe=detalhe)


def _consulta(
    fabrica: sessionmaker[Session],
    cliente: ClienteGranatech | None,
    payload: dict[str, Any],
    servico: AgentService | None = None,
) -> None:
    id_externo = str(payload.get("id_solicitacao") or "")
    novo = str(payload.get("status") or "")

    with abrir_sessao(fabrica) as sessao:
        linha = sessao.scalars(
            select(ConsultaGranatech)
            .where(ConsultaGranatech.id_externo == id_externo)
            .with_for_update()
        ).first()
        if linha is None:
            _alertar(sessao, None, motivo="consulta_desconhecida", id=id_externo, status=novo)
            return

        # Reatribuir a lista inteira: o JSONB não acompanha `append`.
        linha.historico = [*linha.historico, {"status": novo, "recebido_em": _agora()}]
        if novo not in ordem.CONSULTA:
            _alertar(
                sessao, linha.conversa_id, motivo="status_desconhecido", id=id_externo, status=novo
            )
            return
        if ordem.aceita_consulta(linha.status, novo):
            linha.status = novo
            if novo in ordem.CONSULTA_ALERTA:
                _alertar(
                    sessao,
                    linha.conversa_id,
                    motivo="status_de_atencao",
                    id=id_externo,
                    status=novo,
                )
        else:
            logger.info("granatech_consulta_status_ignorado atual=%s novo=%s", linha.status, novo)
        status = linha.status
        tem_detalhe = linha.detalhe is not None
        conversation_id = (
            sessao.scalar(select(Conversa.conversation_id).where(Conversa.id == linha.conversa_id))
            if linha.conversa_id
            else None
        )

    if status == "SUCCESS" and not tem_detalhe:
        if cliente is None:
            return
        if cliente.gravar_detalhe(id_externo) is None:
            raise DetalheAindaNaoPronto(id_externo)
    evento = evento_da_consulta(status)
    if servico is not None and conversation_id and evento:
        servico.continuar(conversation_id, evento)


def evento_da_consulta(status: str) -> str | None:
    """Turno de sistema que cada status de consulta provoca na conversa."""

    if status == "SUCCESS":
        return "consulta_pronta"
    if status == "NO_MARGIN":
        return "consulta_sem_margem"
    if ordem.CONSULTA.get(status) == ordem.FINAL:
        return f"consulta_erro:{status}"
    return None


def _proposta(fabrica: sessionmaker[Session], payload: dict[str, Any]) -> None:
    id_externo = str(payload.get("id_proposta") or "")
    notificacao = payload.get("tipo_notificacao")
    notificacao = str(notificacao) if notificacao else None
    novo = ordem.status_da_proposta(str(payload.get("status_da_proposta") or ""), notificacao)

    with abrir_sessao(fabrica) as sessao:
        linha = sessao.scalars(
            select(PropostaGranatech)
            .where(PropostaGranatech.id_externo == id_externo)
            .with_for_update()
        ).first()
        if linha is None:
            _alertar(sessao, None, motivo="proposta_desconhecida", id=id_externo, status=novo)
            return

        linha.historico = [
            *linha.historico,
            {
                "status": novo,
                "tipo_notificacao": notificacao,
                "informacoes": payload.get("informacoes"),
                "recebido_em": _agora(),
            },
        ]
        if not novo or novo not in ordem.PROPOSTA:
            # O contrato pede handoff para status desconhecido; o alerta é o que
            # existe até a Fase 6 ligar a proposta à conversa.
            _alertar(
                sessao,
                linha.conversa_id,
                motivo="status_desconhecido",
                id=id_externo,
                status=novo,
                tipo_notificacao=notificacao,
            )
            return
        if ordem.aceita_proposta(linha.status, novo, notificacao):
            linha.status = novo
            linha.tipo_notificacao = notificacao
        else:
            logger.info("granatech_proposta_status_ignorado atual=%s novo=%s", linha.status, novo)
