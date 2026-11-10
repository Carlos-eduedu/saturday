# syntax=docker/dockerfile:1

# O contexto de build é a raiz do monorepo: `migrations/` e `alembic.ini` vivem
# lá e precisam entrar na imagem para o serviço `migrate` rodar.

# ---------- Etapa 1: dependências ----------
FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Copie apenas os arquivos de dependência para aproveitar o cache de camadas.
COPY apps/core/pyproject.toml apps/core/uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# Instala o projeto depois de copiar o código, para manter o cache de dependências.
COPY apps/core/src ./src
COPY apps/core/README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# ---------- Etapa 2: runtime ----------
FROM python:3.14-slim AS runtime

RUN groupadd --system --gid 1000 saturday \
    && useradd --system --uid 1000 --gid saturday --create-home saturday

WORKDIR /app

# Ambiente virtual já resolvido na etapa de build.
COPY --from=builder /app/.venv /app/.venv

# Metadados e código da aplicação.
COPY apps/core/pyproject.toml apps/core/uv.lock apps/core/README.md ./
COPY apps/core/src ./src

# Migrações: o serviço `migrate` roda `alembic upgrade head` nesta imagem.
COPY apps/core/alembic.ini ./alembic.ini
COPY apps/core/migrations ./migrations

RUN chown -R saturday:saturday /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Nada é escrito em disco pela aplicação: estado no Postgres, anexos no S3.
# UID numérico: o orquestrador não precisa resolver o nome em /etc/passwd.
USER 1000:1000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"]

CMD ["saturday"]
