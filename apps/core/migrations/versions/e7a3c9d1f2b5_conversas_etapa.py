"""conversas: etapa da jornada

Revision ID: e7a3c9d1f2b5
Revises: d5f2b8c4e1a7
Create Date: 2026-11-12 18:00:00.000000

A lista do painel mostra em que etapa cada conversa está sem ler o checkpoint
do grafo: o serviço copia a etapa para cá ao fim de cada turno.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7a3c9d1f2b5"
down_revision: str | None = "d5f2b8c4e1a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversas", sa.Column("etapa", sa.String(32)))


def downgrade() -> None:
    op.drop_column("conversas", "etapa")
