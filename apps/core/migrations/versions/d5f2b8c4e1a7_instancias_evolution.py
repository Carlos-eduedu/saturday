"""instâncias da Evolution: telefone fixado

Revision ID: d5f2b8c4e1a7
Revises: c3e9a1f7d2b4
Create Date: 2026-11-12 16:00:00.000000

Decisão 0010. ``instancias`` guarda só o telefone da primeira conexão de cada
instância, para recusar a mesma instância reconectada com outro celular.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5f2b8c4e1a7"
down_revision: str | None = "c3e9a1f7d2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "instancias",
        sa.Column("nome", sa.String(64), primary_key=True),
        sa.Column("telefone", sa.String(16), nullable=False),
        sa.Column(
            "fixado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("instancias")
