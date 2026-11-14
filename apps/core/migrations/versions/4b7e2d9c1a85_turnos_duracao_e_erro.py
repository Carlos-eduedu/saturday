"""turnos_duracao_e_erro

Revision ID: 4b7e2d9c1a85
Revises: 29c8ec6a264a
Create Date: 2026-11-13 21:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4b7e2d9c1a85"
down_revision: str | None = "29c8ec6a264a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("turnos", sa.Column("duracao_ms", sa.Integer(), nullable=True))
    op.add_column("turnos", sa.Column("erro", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("turnos", "erro")
    op.drop_column("turnos", "duracao_ms")
