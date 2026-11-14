"""mensagens: turno e chave da mensagem fixa

Revision ID: a4d7e2c9b6f1
Revises: c5a9e3f7b1d4
Create Date: 2026-11-14 12:00:00.000000

Procedência da fala da IA (decisão 0018): o turno que a produziu e a chave da
mensagem fixa usada. Sem backfill: as linhas antigas ficam nulas e o painel
cai no casamento pelo horário só para elas.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4d7e2c9b6f1"
down_revision: str | None = "c5a9e3f7b1d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mensagens", sa.Column("turno_id", sa.BigInteger(), nullable=True))
    op.add_column("mensagens", sa.Column("chave_mensagem", sa.String(length=128), nullable=True))
    op.create_foreign_key(
        "mensagens_turno_id_fkey",
        "mensagens",
        "turnos",
        ["turno_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_mensagens_turno_id", "mensagens", ["turno_id"])


def downgrade() -> None:
    op.drop_index("ix_mensagens_turno_id", table_name="mensagens")
    op.drop_constraint("mensagens_turno_id_fkey", "mensagens", type_="foreignkey")
    op.drop_column("mensagens", "chave_mensagem")
    op.drop_column("mensagens", "turno_id")
