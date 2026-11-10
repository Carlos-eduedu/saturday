"""Base declarativa do SQLAlchemy para todas as tabelas do Saturday."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base declarativa; o Alembic lê ``Base.metadata`` para gerar migrações."""
