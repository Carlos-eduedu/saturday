"""Regras das ações sobre uma conversa: quem pode assumir, devolver, transferir e enviar.

Cada ação roda sob a trava da conversa (a mesma do turno da IA), muda o estado
de atendimento e grava a auditoria na mesma transação.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from saturday.canais.base import CANAIS_WHATSAPP
from saturday.canais.whatsapp.janela import janela_aberta
from saturday.canais.whatsapp.modelos import MODELOS
from saturday.dados import repositorios
from saturday.dados.modelos import Conversa, UsuarioPainel
from saturday.dados.outbox import enfileirar
from saturday.dados.sessao import sessao as abrir_sessao
from saturday.dados.trava import travar_conversa
from saturday.painel.auditoria import auditar

# Modelos que o atendente pode mandar: utilidade e sem botão de link.
# TODO: variáveis de modelo quando os textos forem cadastrados na Meta; os
# links `/l/{codigo}` só existem na Fase 6.
MODELOS_DO_PAINEL = tuple(
    nome
    for nome, modelo in MODELOS.items()
    if modelo.categoria == "utilidade" and not modelo.tem_link
)


class AcaoRecusada(Exception):
    """A ação não vale para este usuário ou para o estado da conversa."""

    def __init__(self, status: int, detalhe: str) -> None:
        super().__init__(detalhe)
        self.status = status
        self.detalhe = detalhe


@contextmanager
def conversa_travada(
    fabrica: sessionmaker[Session], conversa_id: uuid.UUID
) -> Iterator[tuple[Session, Conversa]]:
    """Abre a transação, trava a conversa e a relê já sob a trava."""

    with abrir_sessao(fabrica) as sessao:
        conversation_id = sessao.scalar(
            select(Conversa.conversation_id).where(Conversa.id == conversa_id)
        )
        if conversation_id is None:
            raise AcaoRecusada(404, "conversa não encontrada")
        travar_conversa(sessao, conversation_id)
        conversa = sessao.scalars(
            select(Conversa)
            .where(Conversa.id == conversa_id)
            .execution_options(populate_existing=True)
        ).one()
        yield sessao, conversa


def _exigir_dono(conversa: Conversa, usuario_id: uuid.UUID, gestor: bool) -> None:
    if gestor or conversa.atendente_id == usuario_id:
        return
    raise AcaoRecusada(403, "a conversa é de outro atendente")


def assumir(sessao: Session, conversa: Conversa, usuario_id: uuid.UUID, gestor: bool) -> None:
    """Atendente assume da IA ou do handoff; só o gestor toma de outro atendente."""

    if conversa.atendimento == "assumida":
        if conversa.atendente_id == usuario_id:
            return
        _exigir_dono(conversa, usuario_id, gestor)
    anterior = conversa.atendente_id
    repositorios.mudar_atendimento(sessao, conversa, "assumida", atendente_id=usuario_id)
    auditar(
        sessao,
        usuario_id,
        "assumir",
        str(conversa.id),
        {"de": str(anterior) if anterior else None},
    )


def devolver(sessao: Session, conversa: Conversa, usuario_id: uuid.UUID, gestor: bool) -> None:
    if conversa.atendimento == "ia":
        return
    if conversa.atendimento == "assumida":
        _exigir_dono(conversa, usuario_id, gestor)
    repositorios.mudar_atendimento(sessao, conversa, "ia")
    auditar(sessao, usuario_id, "devolver", str(conversa.id))


def transferir(
    sessao: Session,
    conversa: Conversa,
    usuario_id: uuid.UUID,
    gestor: bool,
    destino_id: uuid.UUID,
) -> None:
    if conversa.atendimento != "assumida":
        raise AcaoRecusada(409, "só conversa assumida pode ser transferida")
    _exigir_dono(conversa, usuario_id, gestor)
    destino = sessao.get(UsuarioPainel, destino_id)
    if destino is None or not destino.ativo:
        raise AcaoRecusada(404, "atendente de destino não encontrado")
    anterior = conversa.atendente_id
    repositorios.mudar_atendimento(sessao, conversa, "assumida", atendente_id=destino_id)
    auditar(
        sessao,
        usuario_id,
        "transferir",
        str(conversa.id),
        {"de": str(anterior), "para": str(destino_id)},
    )


def enviar(
    sessao: Session,
    conversa: Conversa,
    usuario_id: uuid.UUID,
    *,
    texto: str | None,
    modelo: str | None,
) -> int:
    """Grava a mensagem do atendente e o envio no outbox, na mesma transação."""

    if conversa.atendimento != "assumida" or conversa.atendente_id != usuario_id:
        raise AcaoRecusada(409, "assuma a conversa antes de responder")
    if (
        conversa.canal not in CANAIS_WHATSAPP
        or not conversa.telefone
        or not conversa.phone_number_id
    ):
        raise AcaoRecusada(409, "o painel só envia pelo WhatsApp")
    if (texto is None) == (modelo is None):
        raise AcaoRecusada(422, "envie texto ou modelo")
    # Janela e modelos são da Meta; a Evolution só manda texto (decisão 0009).
    meta = conversa.canal == "whatsapp"
    if modelo is not None and (not meta or modelo not in MODELOS_DO_PAINEL):
        raise AcaoRecusada(422, "modelo indisponível no painel")
    if (
        meta
        and texto is not None
        and not janela_aberta(conversa.ultima_entrada_em, datetime.now(UTC))
    ):
        raise AcaoRecusada(409, "janela de 24 h fechada: envie um modelo")

    mensagem_id = repositorios.registrar_saida(
        sessao,
        conversa,
        conteudo=texto if texto is not None else f"[modelo {modelo}]",
        autor="atendente",
        usuario_id=usuario_id,
    )
    payload: dict[str, Any] = {
        "conversation_id": conversa.conversation_id,
        "numero": conversa.telefone,
        "phone_number_id": conversa.phone_number_id,
        "answer": texto or "",
        "mensagem_id": mensagem_id,
    }
    if modelo is not None:
        payload["modelo"] = modelo
    enfileirar(sessao, conversa_id=conversa.id, canal=conversa.canal, payload=payload)
    auditar(
        sessao,
        usuario_id,
        "enviar_mensagem",
        str(conversa.id),
        {"mensagem_id": mensagem_id, "modelo": modelo},
    )
    return mensagem_id
