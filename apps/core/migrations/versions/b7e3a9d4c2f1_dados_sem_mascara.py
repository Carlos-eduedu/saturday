"""usuarios_painel: ve_dados_completos

Revision ID: b7e3a9d4c2f1
Revises: a4d8f2c6e1b9
Create Date: 2026-11-23 10:00:00.000000

Membro que vê os dados pessoais sem máscara no painel (decisão 0037). Todo
mundo começa sem: só o gestor liga.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e3a9d4c2f1"
down_revision: str | None = "a4d8f2c6e1b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "usuarios_painel",
        sa.Column("ve_dados_completos", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("usuarios_painel", "ve_dados_completos")
