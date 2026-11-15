"""usuarios_painel: telefone e foto do perfil

Revision ID: c6d2a9e4f1b7
Revises: b8e1f4a6c3d2
Create Date: 2026-11-15 18:00:00.000000

A seção "Você" de Membros deixa cada pessoa editar o próprio contato e foto.
A foto fica no storage privado; a coluna guarda só a chave.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c6d2a9e4f1b7"
down_revision: str | None = "b8e1f4a6c3d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("usuarios_painel", sa.Column("telefone", sa.String(20), nullable=True))
    op.add_column("usuarios_painel", sa.Column("foto_chave", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("usuarios_painel", "foto_chave")
    op.drop_column("usuarios_painel", "telefone")
