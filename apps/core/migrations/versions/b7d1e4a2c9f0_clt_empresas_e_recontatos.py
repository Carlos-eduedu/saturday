"""clt: cache de empresas e recontatos

Revision ID: b7d1e4a2c9f0
Revises: 9a4c2e7f1b30
Create Date: 2026-11-11 23:00:00.000000

Fase 5. ``empresas_cnpj`` guarda a resposta da BrasilAPI por 30 dias;
``recontatos`` guarda quando voltar a falar com o cliente.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7d1e4a2c9f0"
down_revision: str | None = "9a4c2e7f1b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "empresas_cnpj",
        sa.Column("cnpj", sa.String(14), primary_key=True),
        sa.Column("dados", postgresql.JSONB(), nullable=False),
        sa.Column(
            "buscada_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "recontatos",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "conversa_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversas.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("motivo", sa.String(32), nullable=False),
        sa.Column("quando", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tentativas", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("feito_em", sa.DateTime(timezone=True)),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_recontatos_conversa_id", "recontatos", ["conversa_id"])
    op.create_index("ix_recontatos_pendentes", "recontatos", ["motivo", "quando"])


def downgrade() -> None:
    op.drop_index("ix_recontatos_pendentes", table_name="recontatos")
    op.drop_index("ix_recontatos_conversa_id", table_name="recontatos")
    op.drop_table("recontatos")
    op.drop_table("empresas_cnpj")
