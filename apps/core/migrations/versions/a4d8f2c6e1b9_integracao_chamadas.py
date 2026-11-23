"""integracao_chamadas: histórico de cada chamada de um token ao proxy

Revision ID: a4d8f2c6e1b9
Revises: e1f7c3a9b5d2
Create Date: 2026-11-21 12:00:00.000000

Uma linha por chamada autenticada de uma integração (decisão 0035): molde da
rota, IDs do caminho, status e tempo. Só metadados, nada da query nem do corpo
(regra 9). O worker apaga o que passa de 180 dias.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "a4d8f2c6e1b9"
down_revision: str | None = "e1f7c3a9b5d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "integracao_chamadas",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "integracao_id",
            UUID(as_uuid=True),
            sa.ForeignKey("integracoes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "criada_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("metodo", sa.String(8), nullable=False),
        sa.Column("rota", sa.String(200), nullable=False),
        sa.Column("ids", JSONB(), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("duracao_ms", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_integracao_chamadas_busca", "integracao_chamadas", ["integracao_id", "criada_em"]
    )
    op.create_index("ix_integracao_chamadas_criada_em", "integracao_chamadas", ["criada_em"])


def downgrade() -> None:
    op.drop_index("ix_integracao_chamadas_criada_em", table_name="integracao_chamadas")
    op.drop_index("ix_integracao_chamadas_busca", table_name="integracao_chamadas")
    op.drop_table("integracao_chamadas")
