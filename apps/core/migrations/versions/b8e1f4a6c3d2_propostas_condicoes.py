"""propostas_granatech: condições aceitas

Revision ID: b8e1f4a6c3d2
Revises: a4d7e2c9b6f1
Create Date: 2026-11-14 13:00:00.000000

A simulação que o cliente aceitou fica na proposta, para o painel mostrar as
condições mesmo depois que a conversa seguir. Sem backfill: as propostas
antigas ficam nulas e o painel usa a oferta do checkpoint.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8e1f4a6c3d2"
down_revision: str | None = "a4d7e2c9b6f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "propostas_granatech",
        sa.Column("condicoes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("propostas_granatech", "condicoes")
