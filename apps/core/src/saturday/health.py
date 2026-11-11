"""Saúde do processo, para o healthcheck do container.

A API responde `/health` por HTTP. O worker não serve HTTP: a verificação dele é
o banco acessível e o laço girando (arquivo de batimento recente). Sem isso, um
worker travado aparecia como saudável só porque o processo existia.
"""

from __future__ import annotations

import os
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, literal, select
from sqlalchemy.pool import NullPool

from saturday.settings import Settings, get_settings

BATIMENTO = Path(tempfile.gettempdir()) / "saturday-worker.beat"
LIMITE_BATIMENTO_S = 60


def registrar_batimento(caminho: Path = BATIMENTO) -> None:
    """Marca que o laço deu mais uma volta.

    Falhar aqui é diagnóstico, não operação: não pode derrubar o worker.
    """

    try:
        caminho.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
    except OSError:
        return


def _idade_batimento(caminho: Path) -> float | None:
    try:
        mtime = caminho.stat().st_mtime
    except OSError:
        return None
    return (datetime.now(UTC) - datetime.fromtimestamp(mtime, UTC)).total_seconds()


def problemas(ping: Callable[[], bool], *, caminho: Path = BATIMENTO) -> list[str]:
    """Lista o que está errado. Vazio significa saudável."""

    achados: list[str] = []
    if not ping():
        achados.append("banco inacessível")

    idade = _idade_batimento(caminho)
    if idade is None:
        achados.append("batimento ausente")
    elif idade > LIMITE_BATIMENTO_S:
        achados.append(f"batimento atrasado ({idade:.0f}s)")

    return achados


def _ping(settings: Settings) -> bool:
    url = settings.database_url.get_secret_value()
    if not url:
        return False
    dsn = url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(dsn, poolclass=NullPool)
    try:
        with engine.connect() as conexao:
            conexao.scalar(select(literal(1)))
    except Exception:  # noqa: BLE001 - saúde é booleana: falhou, não interessa o porquê
        return False
    finally:
        engine.dispose()
    return True


URL_PADRAO = "http://127.0.0.1:8000/health"


def _ping_http(url: str | None = None) -> bool:
    """URL configurável: o simulador da Meta serve noutra porta."""

    destino = url or os.environ.get("SATURDAY_HEALTH_URL", URL_PADRAO)
    try:
        with urllib.request.urlopen(destino, timeout=5) as resposta:  # noqa: S310
            codigo = int(resposta.status)
    except urllib.error.URLError, OSError, ValueError:
        return False
    return 200 <= codigo < 300


def main(argv: list[str] | None = None) -> int:
    argumentos = sys.argv[1:] if argv is None else argv
    alvo = argumentos[:1]

    if alvo == ["api"]:
        return 0 if _ping_http() else 1

    if alvo != ["worker"]:
        print("uso: saturday-health api|worker")
        return 2

    settings = get_settings()
    achados = problemas(lambda: _ping(settings))
    if achados:
        print("; ".join(achados))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
