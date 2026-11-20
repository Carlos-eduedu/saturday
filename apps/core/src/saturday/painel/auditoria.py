"""Trilha das ações humanas no painel: quem, o quê, quando e alvo."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from saturday.dados.modelos import Auditoria


def auditar(
    sessao: Session,
    usuario_id: uuid.UUID | None,
    acao: str,
    alvo: str = "",
    detalhe: dict[str, Any] | None = None,
) -> None:
    """Grava na transação da própria ação: ação sem rastro não acontece.

    `usuario_id` nulo: ação de uma integração, que diz quem foi no `detalhe`.
    """

    sessao.add(Auditoria(usuario_id=usuario_id, acao=acao, alvo=alvo, detalhe=detalhe))
    sessao.flush()
