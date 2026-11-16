"""usuarios_painel: função, observação, disponibilidade e último acesso

Revision ID: f3b6d9a2c5e8
Revises: e2a7c4b9d1f6
Create Date: 2026-11-16 16:00:00.000000

Dados da página do membro (decisão 0023). Todo mundo começa disponível e sem
último acesso: ele passa a ser gravado no primeiro uso do painel.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3b6d9a2c5e8"
down_revision: str | None = "e2a7c4b9d1f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("usuarios_painel", sa.Column("cargo", sa.String(60)))
    op.add_column("usuarios_painel", sa.Column("observacao", sa.Text()))
    op.add_column(
        "usuarios_painel",
        sa.Column("disponivel", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("usuarios_painel", sa.Column("ultimo_acesso_em", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("usuarios_painel", "ultimo_acesso_em")
    op.drop_column("usuarios_painel", "disponivel")
    op.drop_column("usuarios_painel", "observacao")
    op.drop_column("usuarios_painel", "cargo")
