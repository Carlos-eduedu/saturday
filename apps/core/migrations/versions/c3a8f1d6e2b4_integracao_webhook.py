"""integração: webhook de saída e dono das consultas e propostas

Revision ID: c3a8f1d6e2b4
Revises: b7e2d5a9c3f1
Create Date: 2026-11-20 15:00:00.000000

A integração ganha o endereço e o segredo do aviso; consulta e proposta abertas
pelo proxy guardam a integração dona; o outbox aceita aviso sem conversa
(decisão 0035, fase 2).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3a8f1d6e2b4"
down_revision: str | None = "b7e2d5a9c3f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _dona(tabela: str, ondelete: str) -> None:
    op.add_column(
        tabela,
        sa.Column(
            "integracao_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("integracoes.id", ondelete=ondelete),
        ),
    )


def upgrade() -> None:
    op.add_column("integracoes", sa.Column("webhook_url", sa.Text()))
    op.add_column("integracoes", sa.Column("webhook_segredo", sa.String(80)))
    _dona("consultas_granatech", "SET NULL")
    _dona("propostas_granatech", "SET NULL")
    _dona("outbox", "CASCADE")
    op.create_index("ix_outbox_integracao_id", "outbox", ["integracao_id"])
    op.alter_column("outbox", "conversa_id", nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM outbox WHERE conversa_id IS NULL")
    op.alter_column("outbox", "conversa_id", nullable=False)
    op.drop_index("ix_outbox_integracao_id", table_name="outbox")
    for tabela in ("outbox", "propostas_granatech", "consultas_granatech"):
        op.drop_column(tabela, "integracao_id")
    op.drop_column("integracoes", "webhook_segredo")
    op.drop_column("integracoes", "webhook_url")
