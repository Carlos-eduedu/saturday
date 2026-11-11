"""outbox: envio que espera o cliente reabrir a janela

Revision ID: 3c1f9a7b2d40
Revises: 7eb63c298d1e
Create Date: 2026-11-11 15:00:00.000000

Com a janela de 24 h fechada sai só o modelo `atualizacao_pedido`; o texto fica
na linha, marcado com o horário do aviso, até o cliente escrever de novo.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3c1f9a7b2d40"
down_revision: str | None = "7eb63c298d1e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "outbox",
        sa.Column("aguardando_cliente_desde", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("outbox", "aguardando_cliente_desde")
