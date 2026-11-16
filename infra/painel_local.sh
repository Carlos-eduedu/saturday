#!/usr/bin/env bash
# Sobe a API e o painel na máquina, para ver telas no navegador.
#
# O `.env` local não tem banco nem os segredos da Meta: aqui eles entram
# fictícios, só para a API passar pelo `validar_para_subir`. Nada sai para a
# Meta (a Graph aponta para o simulador local) nem para o S3.
#
#   infra/painel_local.sh            # API em :8000 e painel em :5173
#   infra/painel_local.sh usuario    # antes, cria um gestor (pede e-mail e senha)
#
# Rode da raiz do repositório (ou da worktree), com o Postgres do compose no ar.
set -euo pipefail

BANCO="${PAINEL_LOCAL_BANCO:-saturday_painel_dev}"
export SATURDAY_DATABASE_URL="postgresql://saturday:saturday@127.0.0.1:5432/${BANCO}"
export SATURDAY_S3_BUCKET=local-ficticio
export SATURDAY_S3_ENDPOINT=http://127.0.0.1:9000
export SATURDAY_S3_ACCESS_KEY=local
export SATURDAY_S3_SECRET_KEY=local-ficticio
export SATURDAY_WHATSAPP_TOKEN=local-ficticio
export SATURDAY_WHATSAPP_APP_SECRET=local-ficticio
export SATURDAY_WHATSAPP_VERIFY_TOKEN=local-ficticio
export SATURDAY_WHATSAPP_NUMEROS=100000000000001
export SATURDAY_WHATSAPP_GRAPH_URL=http://127.0.0.1:8100
SATURDAY_SESSAO_SEGREDO="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export SATURDAY_SESSAO_SEGREDO

# Banco novo nasce vazio; o que já existe só recebe as migrações que faltam.
docker exec saturday-postgres-1 createdb -U saturday "$BANCO" 2>/dev/null || true
uv run --project apps/core alembic -c apps/core/alembic.ini upgrade head

if [ "${1:-}" = "usuario" ]; then
  read -r -p "E-mail do gestor: " email
  uv run --project apps/core saturday criar-usuario --email "$email" --perfil gestor
fi

uv run --project apps/core saturday &
api=$!
trap 'kill "$api" 2>/dev/null || true' EXIT
(cd apps/painel && npm run dev -- --strictPort)
