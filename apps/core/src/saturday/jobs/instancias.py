"""Eventos de conexão das instâncias da Evolution, no worker (decisão 0010).

`open` fixa o telefone da instância; se ela voltou com outro celular, o
Saturday a desconecta na hora e avisa a equipe. Queda definitiva (`close`,
`refused`) vira o alerta "instância desconectada", um por instância enquanto
estiver aberto.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from saturday.canais.evolution.cliente import EvolutionClient
from saturday.dados import instancias, repositorios
from saturday.dados.modelos import Alerta
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.privacidade import mascarar_telefone

logger = logging.getLogger(__name__)

ALERTA_DESCONECTADA = "instancia_desconectada"
ALERTA_NUMERO_TROCADO = "instancia_numero_trocado"


def _alerta_aberto(sessao: Session, tipo: str, instancia: str) -> bool:
    return (
        sessao.scalars(
            select(Alerta.id).where(
                Alerta.tipo == tipo,
                Alerta.resolvido_em.is_(None),
                Alerta.detalhe["instancia"].astext == instancia,
            )
        ).first()
        is not None
    )


def _alertar(sessao: Session, tipo: str, detalhe: dict[str, Any]) -> None:
    if not _alerta_aberto(sessao, tipo, str(detalhe["instancia"])):
        repositorios.abrir_alerta(sessao, tipo, detalhe=detalhe)


def aplicar(
    fabrica: sessionmaker[Session],
    cliente: EvolutionClient | None,
    payload: dict[str, Any],
) -> None:
    instancia = str(payload.get("instancia") or "")
    estado = str(payload.get("estado") or "")
    if not instancia:
        return

    if estado != "open":
        with abrir_sessao(fabrica) as sessao:
            _alertar(
                sessao,
                ALERTA_DESCONECTADA,
                {"instancia": instancia, "estado": estado, "motivo": payload.get("motivo")},
            )
        logger.warning("evolution_instancia_caiu instancia=%s estado=%s", instancia, estado)
        return

    telefone = str(payload.get("telefone") or "")
    if not telefone:
        return
    with abrir_sessao(fabrica) as sessao:
        fixado = instancias.fixar_telefone(sessao, instancia, telefone)
        if fixado == telefone:
            return
        _alertar(
            sessao,
            ALERTA_NUMERO_TROCADO,
            {
                "instancia": instancia,
                "fixado": mascarar_telefone(fixado),
                "recebido": mascarar_telefone(telefone),
            },
        )
    logger.warning("evolution_numero_trocado instancia=%s", instancia)
    # Fora da sessão: falhar aqui devolve o evento à fila, e o alerta já ficou.
    if cliente is None:
        raise RuntimeError("número trocado com o canal Evolution desligado")
    cliente.desconectar(instancia)
