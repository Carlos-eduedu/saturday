"""usuarios_painel: troca de senha obrigatória

Revision ID: d4f8b2a6c1e9
Revises: a1b5c8d3e7f2
Create Date: 2026-11-18 16:00:00.000000

Senha definida pelo gestor (cadastro ou redefinição) liga a marca; a pessoa só
alcança a troca até trocar (decisão 0030). Nasce desligada: quem já tem conta
não é obrigado a trocar.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4f8b2a6c1e9"
down_revision: str | None = "a1b5c8d3e7f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "usuarios_painel",
        sa.Column("trocar_senha", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("usuarios_painel", "trocar_senha")
