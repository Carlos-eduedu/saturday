"""proposta: links curtos e opt-in de marketing

Revision ID: c3e9a1f7d2b4
Revises: b7d1e4a2c9f0
Create Date: 2026-11-12 10:00:00.000000

Fase 6. ``links_curtos`` leva do ``/l/{codigo}`` ao link de biometria vigente;
``conversas.marketing`` guarda o opt-in ou opt-out do modelo de marketing.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3e9a1f7d2b4"
down_revision: str | None = "b7d1e4a2c9f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversas", sa.Column("marketing", sa.String(8)))
    op.create_table(
        "links_curtos",
        sa.Column("codigo", sa.String(16), primary_key=True),
        sa.Column("id_proposta", sa.String(64), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column(
            "criado_em", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_links_curtos_id_proposta", "links_curtos", ["id_proposta"])


def downgrade() -> None:
    op.drop_index("ix_links_curtos_id_proposta", table_name="links_curtos")
    op.drop_table("links_curtos")
    op.drop_column("conversas", "marketing")
