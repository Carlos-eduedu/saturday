"""Engine e sessões do Postgres."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from saturday.settings import Settings


def criar_engine(settings: Settings, *, url: str | None = None) -> Engine:
    """Engine do Postgres.

    ``NullPool`` de propósito: a API e o worker são processos curtos e quem
    administra conexões é o pool do próprio Postgres. Uma conexão presa em
    ``Idle in transaction`` por um pool ocioso é pior do que abrir outra.
    """

    destino = url or settings.database_url.get_secret_value()
    if not destino:
        raise RuntimeError(
            "SATURDAY_DATABASE_URL não definida. Sem Postgres não há estado de conversa: "
            "rode com o profile `postgres` do compose ou aponte uma instância externa."
        )
    return create_engine(destino, pool_pre_ping=True, poolclass=NullPool, future=True)


def criar_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def sessao(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Sessão com commit no sucesso e rollback na exceção."""

    aberta = factory()
    try:
        yield aberta
        aberta.commit()
    except Exception:
        aberta.rollback()
        raise
    finally:
        aberta.close()
