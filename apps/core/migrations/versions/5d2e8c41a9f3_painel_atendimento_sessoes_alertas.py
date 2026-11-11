"""painel: estado de atendimento, autor da mensagem, sessões e alertas

Revision ID: 5d2e8c41a9f3
Revises: 3c1f9a7b2d40
Create Date: 2026-11-11 18:00:00.000000

O estado de atendimento passa a morar em `conversas` (docs/decisoes/0003). As
mensagens já gravadas ganham autor pela direção: entrada é do cliente e saída,
até aqui, só podia ser da IA.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5d2e8c41a9f3"
down_revision: str | None = "3c1f9a7b2d40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversas",
        sa.Column("atendimento", sa.String(16), nullable=False, server_default="ia"),
    )
    op.add_column(
        "conversas",
        sa.Column(
            "atendente_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuarios_painel.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("conversas", sa.Column("atendimento_em", sa.DateTime(timezone=True)))
    op.add_column("conversas", sa.Column("vista_em", sa.DateTime(timezone=True)))
    op.create_index("ix_conversas_atendimento", "conversas", ["atendimento"])

    op.add_column(
        "mensagens",
        sa.Column("autor", sa.String(16), nullable=False, server_default="ia"),
    )
    op.add_column(
        "mensagens",
        sa.Column(
            "usuario_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuarios_painel.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.execute("UPDATE mensagens SET autor = 'cliente' WHERE direcao = 'entrada'")
    op.alter_column("mensagens", "autor", server_default=None)

    op.create_table(
        "sessoes_painel",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "usuario_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuarios_painel.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expira_em", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "criada_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_sessoes_painel_usuario_id", "sessoes_painel", ["usuario_id"])

    op.create_table(
        "alertas",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("tipo", sa.String(32), nullable=False),
        sa.Column(
            "conversa_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversas.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("detalhe", postgresql.JSONB),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "resolvido_por",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("usuarios_painel.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resolvido_em", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_alertas_abertos", "alertas", ["resolvido_em", "criado_em"])


def downgrade() -> None:
    op.drop_index("ix_alertas_abertos", table_name="alertas")
    op.drop_table("alertas")
    op.drop_index("ix_sessoes_painel_usuario_id", table_name="sessoes_painel")
    op.drop_table("sessoes_painel")
    op.drop_column("mensagens", "usuario_id")
    op.drop_column("mensagens", "autor")
    op.drop_index("ix_conversas_atendimento", table_name="conversas")
    op.drop_column("conversas", "vista_em")
    op.drop_column("conversas", "atendimento_em")
    op.drop_column("conversas", "atendente_id")
    op.drop_column("conversas", "atendimento")
