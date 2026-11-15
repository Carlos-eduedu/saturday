"""consultas e propostas da Granatech: marca de teste

Revision ID: e2a7c4b9d1f6
Revises: d8b3f5a1c7e2
Create Date: 2026-11-15 21:00:00.000000

Conversa de membro testador usa o simulador da Granatech (decisão 0020). As
linhas dele ficam marcadas, e o id externo passa a ser único junto com a
marca: o simulador e a Granatech real numeram por conta própria.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2a7c4b9d1f6"
down_revision: str | None = "d8b3f5a1c7e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABELAS = {
    "consultas_granatech": "uq_consultas_granatech_externo_teste",
    "propostas_granatech": "uq_propostas_granatech_externo_teste",
}


def upgrade() -> None:
    op.add_column(
        "links_curtos",
        sa.Column("teste", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    for tabela, nome in TABELAS.items():
        op.add_column(
            tabela,
            sa.Column("teste", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.drop_constraint(f"{tabela}_id_externo_key", tabela, type_="unique")
        op.create_unique_constraint(nome, tabela, ["id_externo", "teste"])


def downgrade() -> None:
    for tabela, nome in TABELAS.items():
        op.execute(sa.text(f"DELETE FROM {tabela} WHERE teste"))  # noqa: S608 - nome fixo
        op.drop_constraint(nome, tabela, type_="unique")
        op.create_unique_constraint(f"{tabela}_id_externo_key", tabela, ["id_externo"])
        op.drop_column(tabela, "teste")
    op.execute(sa.text("DELETE FROM links_curtos WHERE teste"))
    op.drop_column("links_curtos", "teste")
