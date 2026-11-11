"""granatech: consultas e propostas

Revision ID: 9a4c2e7f1b30
Revises: 5d2e8c41a9f3
Create Date: 2026-11-11 21:00:00.000000

Fase 4. A consulta é gravada quando a Granatech a devolve; a proposta nasce
como intenção antes do POST (regra 4 do AGENTS.md).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9a4c2e7f1b30"
down_revision: str | None = "5d2e8c41a9f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "consultas_granatech",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("id_externo", sa.String(64), nullable=False, unique=True),
        sa.Column("cpf", sa.String(11), nullable=False),
        sa.Column(
            "conversa_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversas.id", ondelete="CASCADE"),
        ),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("link_termo", sa.Text()),
        sa.Column("detalhe", postgresql.JSONB()),
        sa.Column("historico", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "criada_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "atualizada_em",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_consultas_granatech_cpf", "consultas_granatech", ["cpf", "criada_em"])

    op.create_table(
        "propostas_granatech",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "consulta_id",
            sa.BigInteger(),
            sa.ForeignKey("consultas_granatech.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversa_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversas.id", ondelete="CASCADE"),
        ),
        sa.Column("id_externo", sa.String(64), unique=True),
        sa.Column("estado_envio", sa.String(16), nullable=False, server_default="intencao"),
        sa.Column("valor_parcela", sa.Numeric(12, 2), nullable=False),
        sa.Column("numero_parcelas", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(64)),
        sa.Column("tipo_notificacao", sa.String(64)),
        sa.Column("historico", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "intencao_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "atualizada_em",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_propostas_granatech_consulta_id", "propostas_granatech", ["consulta_id"])


def downgrade() -> None:
    op.drop_table("propostas_granatech")
    op.drop_index("ix_consultas_granatech_cpf", table_name="consultas_granatech")
    op.drop_table("consultas_granatech")
