"""base_de_conhecimento

Revision ID: c5a9e3f7b1d4
Revises: 8d3f6a1c2e97
Create Date: 2026-11-14 02:00:00.000000

Exige a imagem `pgvector/pgvector:pg17` (decisão 0017): a extensão `vector`
não existe no `postgres:17-alpine`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from saturday.dados.modelos import Vetor

revision: str = "c5a9e3f7b1d4"
down_revision: str | None = "8d3f6a1c2e97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "fontes_conhecimento",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("titulo", sa.String(length=120), nullable=False),
        sa.Column("tipo", sa.String(length=16), nullable=False),
        sa.Column("texto", sa.Text(), nullable=True),
        sa.Column("arquivo_chave", sa.Text(), nullable=True),
        sa.Column("arquivo_nome", sa.String(length=200), nullable=True),
        sa.Column("tamanho", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("erro", sa.String(length=200), nullable=True),
        sa.Column("trechos", sa.Integer(), nullable=False),
        sa.Column("modelo", sa.String(length=128), nullable=True),
        sa.Column("autor_id", sa.UUID(), nullable=True),
        sa.Column(
            "criada_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "atualizada_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("indexada_em", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["autor_id"], ["usuarios_painel.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fontes_conhecimento_status", "fontes_conhecimento", ["status"])
    op.create_table(
        "trechos_conhecimento",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("fonte_id", sa.UUID(), nullable=False),
        sa.Column("ordem", sa.Integer(), nullable=False),
        sa.Column("texto", sa.Text(), nullable=False),
        sa.Column("embedding", Vetor(), nullable=False),
        sa.Column("modelo", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(["fonte_id"], ["fontes_conhecimento.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trechos_conhecimento_fonte_id", "trechos_conhecimento", ["fonte_id"])


def downgrade() -> None:
    op.drop_table("trechos_conhecimento")
    op.drop_table("fontes_conhecimento")
