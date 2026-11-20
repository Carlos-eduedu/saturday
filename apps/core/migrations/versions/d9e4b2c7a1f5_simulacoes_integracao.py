"""simulacoes_integracao: simulações repassadas ao APP MEX

Revision ID: d9e4b2c7a1f5
Revises: c3a8f1d6e2b4
Create Date: 2026-11-20 18:00:00.000000

A proposta criada pelo proxy precisa bater com uma simulação que o Saturday
repassou: o teto é conferido pelo que a Granatech calculou (decisão 0035, fase 3).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d9e4b2c7a1f5"
down_revision: str | None = "c3a8f1d6e2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "simulacoes_integracao",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "integracao_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("integracoes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("id_produto", sa.String(64), nullable=False),
        sa.Column("id_margem", sa.String(64), nullable=False),
        sa.Column("numero_parcelas", sa.Integer(), nullable=False),
        sa.Column("valor_parcela", sa.Numeric(12, 2), nullable=False),
        sa.Column("liberado", sa.Numeric(12, 2), nullable=False),
        sa.Column(
            "criada_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_simulacoes_integracao_busca", "simulacoes_integracao", ["integracao_id", "id_margem"]
    )


def downgrade() -> None:
    op.drop_index("ix_simulacoes_integracao_busca", table_name="simulacoes_integracao")
    op.drop_table("simulacoes_integracao")
