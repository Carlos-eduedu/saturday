"""Trilha das ações humanas no painel: quem, o quê, quando e alvo."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from saturday.dados.modelos import Auditoria


def auditar(
    sessao: Session,
    usuario_id: uuid.UUID,
    acao: str,
    alvo: str = "",
    detalhe: dict[str, Any] | None = None,
) -> None:
    """Grava na transação da própria ação: ação sem rastro não acontece."""

    sessao.add(Auditoria(usuario_id=usuario_id, acao=acao, alvo=alvo, detalhe=detalhe))
    sessao.flush()
