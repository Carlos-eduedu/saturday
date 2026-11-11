"""canal whatsapp: telefone, janela e fila de eventos

Revision ID: 7eb63c298d1e
Revises: 8bfe0738ad5f
Create Date: 2026-11-11 09:40:51.097341

Escrita à mão: o autogenerate deste passo também queria *apagar* as tabelas do
checkpointer do LangGraph (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`),
que existem no banco mas não estão em `Base.metadata`. O `env.py` agora as
ignora, para isso não voltar a acontecer.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7eb63c298d1e"
down_revision: str | None = "8bfe0738ad5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Conversa: telefone, número de origem e a base da janela de 24 h.
    op.add_column("conversas", sa.Column("telefone", sa.String(length=20), nullable=True))
    op.add_column("conversas", sa.Column("phone_number_id", sa.String(length=32), nullable=True))
    op.add_column(
        "conversas",
        sa.Column("ultima_entrada_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_conversas_telefone"), "conversas", ["telefone"], unique=False)

    # Evento de entrada: agora é fila, não só marca de deduplicação.
    op.add_column(
        "eventos_recebidos",
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "eventos_recebidos",
        sa.Column("tentativas", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "eventos_recebidos",
        sa.Column("processado_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "eventos_recebidos",
        sa.Column("falhou_em", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("eventos_recebidos", sa.Column("ultimo_erro", sa.Text(), nullable=True))
    op.create_index(
        "ix_eventos_pendentes",
        "eventos_recebidos",
        ["processado_em", "falhou_em"],
        unique=False,
    )

    # Mensagem: identificação no canal e o status de entrega que a Meta devolve.
    op.add_column("mensagens", sa.Column("wamid", sa.String(length=128), nullable=True))
    op.add_column("mensagens", sa.Column("status_entrega", sa.String(length=16), nullable=True))
    op.create_unique_constraint("uq_mensagens_wamid", "mensagens", ["wamid"])


def downgrade() -> None:
    op.drop_constraint("uq_mensagens_wamid", "mensagens", type_="unique")
    op.drop_column("mensagens", "status_entrega")
    op.drop_column("mensagens", "wamid")

    op.drop_index("ix_eventos_pendentes", table_name="eventos_recebidos")
    op.drop_column("eventos_recebidos", "ultimo_erro")
    op.drop_column("eventos_recebidos", "falhou_em")
    op.drop_column("eventos_recebidos", "processado_em")
    op.drop_column("eventos_recebidos", "tentativas")
    op.drop_column("eventos_recebidos", "payload")

    op.drop_index(op.f("ix_conversas_telefone"), table_name="conversas")
    op.drop_column("conversas", "ultima_entrada_em")
    op.drop_column("conversas", "phone_number_id")
    op.drop_column("conversas", "telefone")
