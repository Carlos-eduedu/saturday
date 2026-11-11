#!/usr/bin/env bash
# Teste de restauração do backup do Postgres do Saturday.
#
# Uso (da raiz do repositório, com Docker):
#   infra/testar_restauracao.sh <arquivo-do-backup>
#
# Aceita o backup do Dokploy (`.sql.gz`, que é um `pg_dump -Fc` comprimido),
# um dump custom (`.dump`) ou SQL puro (`.sql`, `.sql.gz`). Restaura num
# Postgres descartável, confere que a versão das migrações é a head do
# repositório e mostra a contagem das tabelas principais. O container é
# removido no fim, mesmo com erro. Nada é escrito no banco de origem.
set -euo pipefail

DUMP="${1:-}"
if [[ -z "$DUMP" || ! -f "$DUMP" ]]; then
  echo "uso: $0 <arquivo-do-backup>" >&2
  exit 2
fi

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
NOME="saturday-restauracao-$$"
TEMP="$(mktemp -d)"
TABELAS=(conversas mensagens consentimentos consultas_granatech propostas_granatech outbox)

limpar() {
  docker rm -f "$NOME" >/dev/null 2>&1 || true
  rm -rf "$TEMP"
}
trap limpar EXIT

# Descomprime, se for o caso, e descobre o formato pelo cabeçalho.
ARQUIVO="$TEMP/backup"
if gzip -t "$DUMP" 2>/dev/null; then
  gunzip -c "$DUMP" >"$ARQUIVO"
else
  cp "$DUMP" "$ARQUIVO"
fi
if [[ "$(head -c 5 "$ARQUIVO")" == "PGDMP" ]]; then
  FORMATO=custom
else
  FORMATO=sql
fi
echo "Formato do backup: $FORMATO"

docker run -d --rm --name "$NOME" \
  -e POSTGRES_USER=saturday -e POSTGRES_PASSWORD=restauracao -e POSTGRES_DB=saturday \
  postgres:17-alpine >/dev/null
for _ in $(seq 1 60); do
  docker exec "$NOME" pg_isready -U saturday -d saturday >/dev/null 2>&1 && break
  sleep 1
done
# `pg_isready` responde antes do fim da inicialização: espera o banco aceitar consulta.
until docker exec "$NOME" psql -U saturday -d saturday -tAc "select 1" >/dev/null 2>&1; do
  sleep 1
done

if [[ "$FORMATO" == custom ]]; then
  docker exec -i "$NOME" pg_restore --no-owner --no-acl -U saturday -d saturday <"$ARQUIVO"
else
  docker exec -i "$NOME" psql -q -v ON_ERROR_STOP=1 -U saturday -d saturday <"$ARQUIVO" >/dev/null
fi

consultar() {
  docker exec "$NOME" psql -U saturday -d saturday -tAc "$1"
}

ESPERADA="$(cd "$RAIZ/apps/core" && uv run --quiet alembic heads | awk '{print $1}')"
RESTAURADA="$(consultar "select version_num from alembic_version")"
echo "Migração restaurada: $RESTAURADA (head do repositório: $ESPERADA)"

FALHOU=0
if [[ "$RESTAURADA" != "$ESPERADA" ]]; then
  echo "AVISO: o backup é de outra versão das migrações; rode 'alembic upgrade head' depois de restaurar." >&2
fi
for tabela in "${TABELAS[@]}"; do
  if [[ "$(consultar "select to_regclass('public.$tabela') is not null")" != "t" ]]; then
    echo "FALTA a tabela $tabela" >&2
    FALHOU=1
    continue
  fi
  printf '%-22s %s linhas\n' "$tabela" "$(consultar "select count(*) from $tabela")"
done

if [[ "$FALHOU" == 1 ]]; then
  echo "Restauração REPROVADA." >&2
  exit 1
fi
echo "Restauração OK."
