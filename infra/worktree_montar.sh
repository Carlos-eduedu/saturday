#!/usr/bin/env bash
# Monta a worktree corrente para trabalhar: dependências e banco de teste dela.
#
#   infra/worktree_montar.sh            # só o core
#   infra/worktree_montar.sh painel     # também instala o painel
#
# Rode da raiz da worktree (.claude/worktrees/<nome>), com o Postgres no ar.
set -euo pipefail

nome="$(basename "$PWD")"
uv sync --locked -q
if [ "${1:-}" = "painel" ]; then
  (cd apps/painel && npm ci --silent)
fi
docker exec saturday-postgres-1 createdb -U saturday "saturday_test_${nome}" 2>/dev/null || true
echo "SATURDAY_TEST_DATABASE_URL=postgresql://saturday:saturday@127.0.0.1:5432/saturday_test_${nome}"
