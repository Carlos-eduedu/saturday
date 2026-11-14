"""config_agente_e_catalogo

Revision ID: 8d3f6a1c2e97
Revises: 4b7e2d9c1a85
Create Date: 2026-11-14 01:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8d3f6a1c2e97"
down_revision: str | None = "4b7e2d9c1a85"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "usuarios_painel",
        sa.Column("pode_editar_agente", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    # Alguém precisa poder editar logo depois do deploy: os gestores ativos.
    op.execute(
        "UPDATE usuarios_painel SET pode_editar_agente = true WHERE perfil = 'gestor' AND ativo"
    )
    op.create_table(
        "config_agente",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("versao", sa.Integer(), nullable=False),
        sa.Column("modelos", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("nota", sa.String(length=280), nullable=True),
        sa.Column("restaurada_de", sa.Integer(), nullable=True),
        sa.Column("autor_id", sa.UUID(), nullable=True),
        sa.Column(
            "criada_em", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["autor_id"], ["usuarios_painel.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("versao"),
    )
    op.create_table(
        "catalogo_modelos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("fonte", sa.Text(), nullable=False),
        sa.Column("modelos", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "buscado_em",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("catalogo_modelos")
    op.drop_table("config_agente")
    op.drop_column("usuarios_painel", "pode_editar_agente")
