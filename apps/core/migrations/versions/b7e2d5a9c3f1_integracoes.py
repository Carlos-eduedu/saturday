"""integracoes: tokens do proxy da Granatech para o APP MEX

Revision ID: b7e2d5a9c3f1
Revises: d4f8b2a6c1e9
Create Date: 2026-11-20 12:00:00.000000

Cada linha é um acesso de sistema de fora, com nome, escopos e o sha256 do
token, gerado e revogado pelo gestor na página Integrações (decisão 0035).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7e2d5a9c3f1"
down_revision: str | None = "d4f8b2a6c1e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "integracoes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("nome", sa.String(80), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("escopos", postgresql.JSONB(), nullable=False),
        sa.Column(
            "criada_por",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuarios_painel.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "criada_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("revogada_em", sa.DateTime(timezone=True)),
        sa.Column("ultimo_uso_em", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("integracoes")
