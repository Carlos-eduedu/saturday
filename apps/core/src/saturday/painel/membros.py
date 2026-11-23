"""Dados da página do membro (decisão 0023): estado, atividade e últimas ações.

Tudo sai do que o painel já grava (mensagens e auditoria); nada é estimado.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from saturday.dados.modelos import Auditoria, Mensagem, UsuarioPainel

# A sessão dura 8 h: sessão aberta não diz se a pessoa está no painel.
JANELA_NO_PAINEL = timedelta(minutes=5)
# Um pedido por clique não pode virar uma escrita por clique.
INTERVALO_DE_ACESSO = timedelta(minutes=1)
PERIODO_DE_ATIVIDADE = timedelta(days=7)
ULTIMAS_ACOES = 10

# Ações cujo `alvo` na auditoria é o id da conversa.
_ACOES_DE_CONVERSA = frozenset(
    {
        "assumir",
        "devolver",
        "desfazer",
        "transferir",
        "enviar_mensagem",
        "enviar_anexo",
        "conversa:editar_ficha",
        "ver_sem_mascara",
    }
)
_CONTADAS = {"assumir": "assumidas", "devolver": "devolvidas", "transferir": "transferidas"}


def estado(usuario: UsuarioPainel, agora: datetime) -> str:
    """`ausente` (a pessoa marcou), `disponivel` (no painel agora) ou `fora`."""

    if not usuario.disponivel:
        return "ausente"
    acesso = usuario.ultimo_acesso_em
    if acesso is not None and agora - acesso < JANELA_NO_PAINEL:
        return "disponivel"
    return "fora"


def marcar_acesso(usuario: UsuarioPainel, agora: datetime) -> None:
    acesso = usuario.ultimo_acesso_em
    if acesso is None or agora - acesso >= INTERVALO_DE_ACESSO:
        usuario.ultimo_acesso_em = agora


def atividade(sessao: Session, usuario_id: uuid.UUID, agora: datetime) -> dict[str, int]:
    """Mensagens enviadas e conversas assumidas, devolvidas e transferidas em 7 dias."""

    desde = agora - PERIODO_DE_ATIVIDADE
    mensagens = sessao.scalar(
        select(func.count())
        .select_from(Mensagem)
        .where(
            Mensagem.autor == "atendente",
            Mensagem.usuario_id == usuario_id,
            Mensagem.criada_em >= desde,
        )
    )
    por_acao = dict(
        sessao.execute(
            select(Auditoria.acao, func.count())
            .where(
                Auditoria.usuario_id == usuario_id,
                Auditoria.acao.in_(_CONTADAS),
                Auditoria.criada_em >= desde,
            )
            .group_by(Auditoria.acao)
        ).all()
    )
    return {
        "mensagens": int(mensagens or 0),
        **{nome: int(por_acao.get(acao, 0)) for acao, nome in _CONTADAS.items()},
    }


def ultimas_acoes(sessao: Session, usuario_id: uuid.UUID) -> list[dict[str, Any]]:
    """O tipo da ação, a hora e a conversa; nunca o detalhe gravado na auditoria."""

    linhas = sessao.execute(
        select(Auditoria.acao, Auditoria.alvo, Auditoria.criada_em)
        .where(Auditoria.usuario_id == usuario_id)
        .order_by(Auditoria.id.desc())
        .limit(ULTIMAS_ACOES)
    ).all()
    return [
        {
            "acao": acao,
            "quando": quando.isoformat(),
            "conversa_id": alvo
            if acao in _ACOES_DE_CONVERSA or acao.startswith("revelar:")
            else None,
        }
        for acao, alvo, quando in linhas
    ]
