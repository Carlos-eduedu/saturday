# syntax=docker/dockerfile:1

# ---------- Etapa 1: dependências ----------
FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Copie apenas os arquivos de dependência para aproveitar o cache de camadas.
COPY pyproject.toml uv.lock ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# Instala o projeto depois de copiar o código, para manter o cache de dependências.
COPY src ./src
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# ---------- Etapa 2: runtime ----------
FROM python:3.14-slim AS runtime

# Usuário sem privilégios.
RUN groupadd --system --gid 1000 saturday \
    && useradd --system --uid 1000 --gid saturday --create-home saturday

WORKDIR /app

# Ambiente virtual já resolvido na etapa de build.
COPY --from=builder /app/.venv /app/.venv

# Metadados da aplicação.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

# Volume para o SQLite dos checkpoints.
RUN mkdir -p /app/data && chown -R saturday:saturday /app

ENV PATH="/app/.venv/bin:$PATH" \
    SATURDAY_CHECKPOINT_PATH=/app/data/checkpoints.sqlite \
    PYTHONUNBUFFERED=1

USER saturday

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')" || exit 1

# Um único worker: o estado das conversas vive no SQLite local.
CMD ["saturday"]
