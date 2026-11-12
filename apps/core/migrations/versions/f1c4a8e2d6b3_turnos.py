"""turnos: trilha e custo de cada turno da IA

Revision ID: f1c4a8e2d6b3
Revises: e7a3c9d1f2b5
Create Date: 2026-11-12 19:00:00.000000

Uma linha por turno com o caminho no grafo, a classificação, as chamadas
externas (status, tempo, custo e tokens) e os totais. Só metadados: nenhum
texto do cliente ou do modelo (regra 9).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "f1c4a8e2d6b3"
down_revision: str | None = "e7a3c9d1f2b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "turnos",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "conversa_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("caminho", JSONB(), nullable=False),
        sa.Column("status", sa.String(32)),
        sa.Column("motivo", sa.String(64)),
        sa.Column("etapa", sa.String(32)),
        sa.Column("classificacao", JSONB()),
        sa.Column("chamadas", JSONB(), nullable=False),
        sa.Column("custo_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_turnos_conversa_criado", "turnos", ["conversa_id", "criado_em"])
    op.create_index("ix_turnos_criado_em", "turnos", ["criado_em"])


def downgrade() -> None:
    op.drop_index("ix_turnos_criado_em", table_name="turnos")
    op.drop_index("ix_turnos_conversa_criado", table_name="turnos")
    op.drop_table("turnos")
