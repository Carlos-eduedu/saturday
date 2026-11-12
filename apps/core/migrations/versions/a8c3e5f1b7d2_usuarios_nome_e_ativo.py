"""usuarios_painel: nome e ativo

Revision ID: a8c3e5f1b7d2
Revises: f1c4a8e2d6b3
Create Date: 2026-11-12 21:00:00.000000

A aba Usuários do painel cadastra, edita e desativa usuários. O nome substitui
o e-mail na tela; quem já existe recebe o trecho do e-mail antes do `@`.
Desativar nunca apaga a linha, para a auditoria seguir dizendo quem fez o quê
(decisão 0012).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8c3e5f1b7d2"
down_revision: str | None = "f1c4a8e2d6b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("usuarios_painel", sa.Column("nome", sa.String(80)))
    op.execute("UPDATE usuarios_painel SET nome = left(split_part(email, '@', 1), 80)")
    op.alter_column("usuarios_painel", "nome", nullable=False)
    op.add_column(
        "usuarios_painel",
        sa.Column("ativo", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("usuarios_painel", "ativo")
    op.drop_column("usuarios_painel", "nome")
