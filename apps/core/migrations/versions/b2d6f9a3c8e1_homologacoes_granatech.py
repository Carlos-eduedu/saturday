"""homologacoes_granatech: rodadas da homologação pedidas pelo painel

Revision ID: b2d6f9a3c8e1
Revises: a8c3e5f1b7d2
Create Date: 2026-11-13 10:00:00.000000

Uma linha por rodada (decisão 0014), com os passos e os itens em JSONB. O
índice parcial único deixa só uma rodada pendente ou em andamento por vez.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "b2d6f9a3c8e1"
down_revision: str | None = "a8c3e5f1b7d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "homologacoes_granatech",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("fase", sa.Integer(), nullable=False),
        sa.Column("situacao", sa.String(16), nullable=False),
        sa.Column(
            "pedido_por",
            UUID(as_uuid=True),
            sa.ForeignKey("usuarios_painel.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("iniciado_em", sa.DateTime(timezone=True)),
        sa.Column("terminado_em", sa.DateTime(timezone=True)),
        sa.Column("erro", sa.Text()),
        sa.Column("passos", JSONB(), nullable=False),
        sa.Column("itens", JSONB(), nullable=False),
        sa.Column("ids_externos", JSONB(), nullable=False),
    )
    op.create_index(
        "ux_homologacoes_granatech_aberta",
        "homologacoes_granatech",
        [sa.text("(true)")],
        unique=True,
        postgresql_where=sa.text("situacao IN ('pendente', 'em_andamento')"),
    )


def downgrade() -> None:
    op.drop_index("ux_homologacoes_granatech_aberta", table_name="homologacoes_granatech")
    op.drop_table("homologacoes_granatech")
