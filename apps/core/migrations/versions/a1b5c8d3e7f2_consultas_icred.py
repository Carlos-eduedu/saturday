"""consultas do iCred

Revision ID: a1b5c8d3e7f2
Revises: f3b6d9a2c5e8
Create Date: 2026-11-16 18:00:00.000000

Consulta aberta no motor do iCred (decisão 0027), gravada como intenção antes
do POST.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b5c8d3e7f2"
down_revision: str | None = "f3b6d9a2c5e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "consultas_icred",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("chave", sa.String(length=36), nullable=False),
        sa.Column("id_externo", sa.String(length=64), nullable=True),
        sa.Column("cpf", sa.String(length=11), nullable=False),
        sa.Column("conversa_id", sa.Uuid(), nullable=True),
        sa.Column("estado", sa.String(length=16), nullable=False),
        sa.Column("situacao", sa.String(length=32), nullable=True),
        sa.Column("contratos", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("valido_ate", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "criada_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "atualizada_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["conversa_id"], ["conversas.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chave"),
        sa.UniqueConstraint("id_externo"),
    )
    op.create_index("ix_consultas_icred_conversa", "consultas_icred", ["conversa_id", "criada_em"])


def downgrade() -> None:
    op.drop_index("ix_consultas_icred_conversa", table_name="consultas_icred")
    op.drop_table("consultas_icred")
