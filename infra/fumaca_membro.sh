#!/usr/bin/env bash
# Fumaça dos comandos do membro testador, ponta a ponta, sem telefone de verdade.
#
# Sobe a API, o worker e os simuladores da Meta e da Granatech na máquina, cria
# um membro testador num banco descartável e manda os comandos pelo simulador
# da Meta (roteiro em infra/fumaca_membro.py). Nada sai para fora: todo
# parceiro aponta para 127.0.0.1 e os segredos são fictícios.
#
#   infra/fumaca_membro.sh
#
# Rode da raiz do repositório (ou da worktree), com o Postgres do compose no ar
# e as portas 8000, 8100 e 8200 livres. Os logs ficam na pasta impressa no fim.
set -euo pipefail

BANCO=saturday_fumaca_test
TOKEN_SIMULADOR=token-do-simulador-local
export SATURDAY_ENVIRONMENT=dev
export SATURDAY_DATABASE_URL="postgresql://saturday:saturday@127.0.0.1:5432/${BANCO}"
export SATURDAY_OPENROUTER_API_KEY=local-ficticio
export SATURDAY_WEBHOOK_URL=
# O serviço exige um bucket para subir; os comandos não tocam em arquivo.
export SATURDAY_S3_BUCKET=local-ficticio
export SATURDAY_S3_ENDPOINT=http://127.0.0.1:9090
export SATURDAY_S3_ACCESS_KEY=local
export SATURDAY_S3_SECRET_KEY=local-ficticio
export SATURDAY_EVOLUTION_ATIVO=false
export SATURDAY_WHATSAPP_TOKEN=local-ficticio
export SATURDAY_WHATSAPP_APP_SECRET=local-ficticio
export SATURDAY_WHATSAPP_VERIFY_TOKEN=local-ficticio
export SATURDAY_WHATSAPP_NUMEROS=100000000000001
export SATURDAY_WHATSAPP_GRAPH_URL=http://127.0.0.1:8100
export SATURDAY_GRANATECH_ATIVO=true
export SATURDAY_GRANATECH_PROPOSTA_ATIVA=false
# A "real" também é o simulador: nenhuma chamada chega à Granatech.
export SATURDAY_GRANATECH_BASE_URL=http://127.0.0.1:8200
export SATURDAY_GRANATECH_CHAVE_API=chave-do-simulador
export SATURDAY_GRANATECH_WEBHOOK_TOKEN=token-da-real-local
export SATURDAY_GRANATECH_SIMULADOR_URL=http://127.0.0.1:8200
export SATURDAY_GRANATECH_SIMULADOR_CHAVE=chave-do-simulador
export SATURDAY_GRANATECH_SIMULADOR_WEBHOOK_TOKEN="$TOKEN_SIMULADOR"
SATURDAY_SESSAO_SEGREDO="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export SATURDAY_SESSAO_SEGREDO

logs="$(mktemp -d)"
docker exec saturday-postgres-1 dropdb -U saturday --if-exists "$BANCO"
docker exec saturday-postgres-1 createdb -U saturday "$BANCO"
uv run --project apps/core alembic -c apps/core/alembic.ini upgrade head >"$logs/alembic.log" 2>&1
uv run --project apps/core python infra/fumaca_membro.py membro

pids=()
trap 'kill "${pids[@]}" 2>/dev/null || true' EXIT

SIMULADOR_SATURDAY_URL=http://127.0.0.1:8000 SIMULADOR_ATRASO_DETALHE_S=1 \
  SIMULADOR_GRANATECH_CHAVE=chave-do-simulador \
  SATURDAY_GRANATECH_WEBHOOK_TOKEN="$TOKEN_SIMULADOR" \
  uv run --project simuladores uvicorn app:app --app-dir simuladores/granatech --port 8200 \
  >"$logs/granatech.log" 2>&1 &
pids+=($!)
SIMULADOR_SATURDAY_URL=http://127.0.0.1:8000 \
  uv run --project simuladores/meta uvicorn app:app --app-dir simuladores/meta --port 8100 \
  >"$logs/meta.log" 2>&1 &
pids+=($!)
uv run --project apps/core saturday >"$logs/api.log" 2>&1 &
pids+=($!)
uv run --project apps/core saturday-worker >"$logs/worker.log" 2>&1 &
pids+=($!)

for porta in 8000 8100 8200; do
  for _ in $(seq 60); do
    curl -s -o /dev/null "http://127.0.0.1:${porta}/" && break
    sleep 1
  done
done

echo "logs em $logs"
curl -sf -o /dev/null http://127.0.0.1:8000/health || {
  echo "a API não subiu:" >&2
  tail -n 5 "$logs/api.log" >&2
  exit 1
}
uv run --project apps/core python infra/fumaca_membro.py conversa
