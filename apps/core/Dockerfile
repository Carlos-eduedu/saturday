# syntax=docker/dockerfile:1

# O contexto de build é a raiz do monorepo: o `uv.lock` e o `pyproject.toml` do
# workspace vivem aqui. A imagem instala só o pacote `saturday` (`--package`),
# não os simuladores.

# ---------- Etapa 1: dependências ----------
FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Metadados do workspace e dos membros: basta para resolver e cachear.
COPY pyproject.toml uv.lock ./
COPY apps/core/pyproject.toml ./apps/core/pyproject.toml
COPY simuladores/pyproject.toml ./simuladores/pyproject.toml

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project --package saturday

# Instala o projeto depois de copiar o código, para manter o cache de dependências.
COPY apps/core/src ./apps/core/src
COPY apps/core/README.md ./apps/core/README.md
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --package saturday

# ---------- Etapa 2: runtime ----------
FROM python:3.14-slim AS runtime

# ffmpeg: o worker converte o áudio gravado no painel em voz (ogg/opus) para a
# Meta (`canais/whatsapp/audio.py`). Roda por pipe, sem gravar em disco.
RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 1000 saturday \
    && useradd --system --uid 1000 --gid saturday --create-home saturday

WORKDIR /app

# Ambiente virtual já resolvido no build, com o pacote instalado.
COPY --from=builder /app/.venv /app/.venv

# Migrações: o serviço `migrate` roda `alembic upgrade head` nesta imagem.
COPY apps/core/alembic.ini ./alembic.ini
COPY apps/core/migrations ./migrations

# Mensagens fixas por produto (`conhecimento/clt/mensagens.yaml`), lidas a
# partir do diretório de trabalho.
COPY conhecimento ./conhecimento

RUN chown -R saturday:saturday /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Nada é escrito em disco pela aplicação: estado no Postgres, anexos no S3.
# UID numérico: o orquestrador não precisa resolver o nome em /etc/passwd.
USER 1000:1000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["saturday-health", "api"]

CMD ["saturday"]
