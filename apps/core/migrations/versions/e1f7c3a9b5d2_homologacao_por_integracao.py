"""homologacoes_granatech: rodada pedida por uma integração

Revision ID: e1f7c3a9b5d2
Revises: d9e4b2c7a1f5
Create Date: 2026-11-20 20:00:00.000000

O APP MEX pede rodadas pelo proxy (decisão 0035, fase 4): a rodada guarda a
integração no lugar do usuário do painel.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e1f7c3a9b5d2"
down_revision: str | None = "d9e4b2c7a1f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "homologacoes_granatech",
        sa.Column(
            "integracao_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("integracoes.id", ondelete="SET NULL"),
        ),
    )


def downgrade() -> None:
    op.drop_column("homologacoes_granatech", "integracao_id")
