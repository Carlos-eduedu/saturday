"""usuarios_painel: permissão "testar fluxos"

Revision ID: d8b3f5a1c7e2
Revises: c6d2a9e4f1b7
Create Date: 2026-11-15 20:00:00.000000

Conversa vinda do telefone de quem tem a permissão é de membro testador:
selo no painel, fora dos custos, `/reiniciar`, Granatech simulada (dev e
homolog) e esperas encurtadas (decisão 0020). Ninguém começa com ela.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8b3f5a1c7e2"
down_revision: str | None = "c6d2a9e4f1b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "usuarios_painel",
        sa.Column("pode_testar_fluxos", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("usuarios_painel", "pode_testar_fluxos")
