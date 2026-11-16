"""Mudança do estado de atendimento, com os alertas que cada uma abre e resolve.

Quem responde a conversa (`ia`, `handoff` ou `assumida`) só muda por aqui: cada
verbo grava o estado, avisa o painel e cuida dos alertas dele
(docs/decisoes/0018 e 0021). Regra de dono, auditoria e checkpoint ficam com
quem chama.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from saturday.dados import repositorios
from saturday.dados.modelos import Alerta, Conversa

# Alertas que dizem por que a conversa está em handoff.
TIPOS_DE_HANDOFF = ("handoff", "erro_interno", "atendente_desativado")
# O que cada verbo dá por tratado. Transferir não resolve nada, e
# `evento_com_humano` nunca se resolve sozinho.
_RESOLVIDOS_AO_ASSUMIR = TIPOS_DE_HANDOFF
_RESOLVIDOS_AO_DEVOLVER = (*TIPOS_DE_HANDOFF, "sem_resposta")


def _mudar(
    sessao: Session, conversa: Conversa, atendimento: str, atendente_id: uuid.UUID | None = None
) -> None:
    conversa.atendimento = atendimento
    conversa.atendente_id = atendente_id if atendimento == "assumida" else None
    conversa.atendimento_em = func.now()
    sessao.flush()
    repositorios.notificar(sessao, "conversa", conversa=conversa.id)


def assumir(sessao: Session, conversa: Conversa, atendente_id: uuid.UUID) -> list[int]:
    """O atendente vira dono da conversa. Devolve os ids dos alertas resolvidos."""

    _mudar(sessao, conversa, "assumida", atendente_id)
    return repositorios.resolver_alertas(sessao, conversa.id, _RESOLVIDOS_AO_ASSUMIR, atendente_id)


def devolver(sessao: Session, conversa: Conversa, por: uuid.UUID | None) -> list[int]:
    """A conversa volta à IA. Devolve os ids dos alertas resolvidos.

    `por` é quem agiu; `None` quando ela voltou sozinha (prazo do handoff).
    """

    _mudar(sessao, conversa, "ia")
    return repositorios.resolver_alertas(sessao, conversa.id, _RESOLVIDOS_AO_DEVOLVER, por)


def entrar_em_handoff(
    sessao: Session,
    conversa: Conversa,
    tipo_alerta: str,
    detalhe: dict[str, Any] | None = None,
) -> Alerta:
    """A conversa fica sem dono, à espera de um humano, com o alerta que diz por quê.

    Não abre um segundo alerta do mesmo tipo se já houver um aberto na conversa.
    """

    _mudar(sessao, conversa, "handoff")
    return repositorios.abrir_alerta(
        sessao, tipo_alerta, conversa_id=conversa.id, detalhe=detalhe, unico=True
    )


def transferir(sessao: Session, conversa: Conversa, destino_id: uuid.UUID) -> None:
    """Troca o dono. Não resolve alerta: a conversa continua com humano."""

    _mudar(sessao, conversa, "assumida", destino_id)


def restaurar(
    sessao: Session, conversa: Conversa, atendimento: str, atendente_id: uuid.UUID | None
) -> None:
    """Volta ao estado de antes, sem mexer em alerta. Só o desfazer usa."""

    _mudar(sessao, conversa, atendimento, atendente_id)
