"""Ambiente do Alembic.

A URL vem de `SATURDAY_DATABASE_URL`, lida pela própria aplicação, para que
migração e runtime nunca discordem sobre qual banco é o certo.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.sql.schema import SchemaItem

from saturday.dados import modelos  # noqa: F401  (registra as tabelas em Base)
from saturday.dados.base import Base
from saturday.settings import Settings

config = context.config
target_metadata = Base.metadata

# Tabelas que existem no banco mas não são nossas: o checkpointer do LangGraph
# cria e evolui as dele. Sem esta lista, o autogenerate conclui que elas
# "sobraram" e gera `drop_table` — o que apagaria todo o estado das conversas.
TABELAS_DE_TERCEIROS = frozenset(
    {
        "alembic_version",
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
        "checkpoint_migrations",
    }
)


def incluir_objeto(
    objeto: SchemaItem,
    nome: str | None,
    tipo: str,
    _refletido: bool,
    _comparado: SchemaItem | None,
) -> bool:
    if tipo == "table":
        return nome not in TABELAS_DE_TERCEIROS
    pai = getattr(objeto, "table", None)
    return getattr(pai, "name", None) not in TABELAS_DE_TERCEIROS


def _url() -> str:
    url = Settings().database_url.get_secret_value()
    if not url:
        raise RuntimeError(
            "SATURDAY_DATABASE_URL não definida: o Alembic precisa saber em qual "
            "banco aplicar as migrações."
        )
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        include_object=incluir_objeto,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    secao = config.get_section(config.config_ini_section) or {}
    secao["sqlalchemy.url"] = _url()
    engine = engine_from_config(secao, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with engine.connect() as conexao:
        context.configure(
            connection=conexao,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=incluir_objeto,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
