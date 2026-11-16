#!/usr/bin/env bash
# Sobe a API e o painel na máquina, para ver telas no navegador.
#
# O `.env` local não tem banco nem os segredos da Meta: aqui eles entram
# fictícios, só para a API passar pelo `validar_para_subir`. Nada sai para a
# Meta (a Graph aponta para o simulador local); os anexos vão para um S3 de
# mentira na máquina (`saturday-s3-local`, porta 9090), que o `seed` cria.
#
#   infra/painel_local.sh            # API em :8000 e painel em :5173
#   infra/painel_local.sh usuario    # antes, cria um gestor (pede e-mail e senha)
#   infra/painel_local.sh seed       # antes, cria o gestor, as conversas e os anexos de
#                                    # infra/painel_seed.py e .sql; imprime a senha
#                                    # (ou use PAINEL_LOCAL_SENHA, 12+ caracteres)
#
# Rode da raiz do repositório (ou da worktree), com o Postgres do compose no ar.
set -euo pipefail

BANCO="${PAINEL_LOCAL_BANCO:-saturday_painel_dev}"
export SATURDAY_DATABASE_URL="postgresql://saturday:saturday@127.0.0.1:5432/${BANCO}"
export SATURDAY_S3_BUCKET=local-ficticio
export SATURDAY_S3_ENDPOINT=http://127.0.0.1:9090
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

# O S3 local do seed, se já existe, volta a subir: sem ele a mídia responde 404.
docker start saturday-s3-local >/dev/null 2>&1 || true

if [ "${1:-}" = "seed" ]; then
  # Só cria o container que ainda não existe: o que acabou de voltar a subir
  # demora uns segundos para responder, e a espera abaixo cobre os dois casos.
  if ! docker inspect saturday-s3-local >/dev/null 2>&1; then
    # adobe/s3mock: aceita qualquer credencial e já nasce com o bucket. A
    # imagem minio/minio saiu do Docker Hub.
    # shortcut: sem volume, os arquivos somem quando o container reinicia;
    # ganha um volume quando um banco local precisar durar mais que ele.
    docker run -d --name saturday-s3-local -p 9090:9090 \
      -e COM_ADOBE_TESTING_S3MOCK_STORE_INITIAL_BUCKETS="$SATURDAY_S3_BUCKET" \
      -e initialBuckets="$SATURDAY_S3_BUCKET" \
      adobe/s3mock:latest >/dev/null
  fi
  for _ in $(seq 30); do
    curl -sf -o /dev/null "$SATURDAY_S3_ENDPOINT" && break
    sleep 1
  done
  uv run --project apps/core python infra/painel_seed.py
  docker exec -i saturday-postgres-1 psql -q -U saturday -d "$BANCO" < infra/painel_seed.sql
fi

uv run --project apps/core saturday &
api=$!
trap 'kill "$api" 2>/dev/null || true' EXIT
(cd apps/painel && npm run dev -- --strictPort)
