#!/usr/bin/env bash
# Roda as checagens do core na worktree corrente, com o banco de teste dela.
#
#   infra/worktree_testar.sh                       # ruff, mypy e a suíte inteira
#   infra/worktree_testar.sh tests/test_x.py -x    # só o pytest, com estes argumentos
#
# Rode da raiz da worktree (.claude/worktrees/<nome>), depois do
# infra/worktree_montar.sh. Os simuladores entram na rodada completa.
set -euo pipefail

nome="$(basename "$PWD")"
export SATURDAY_TEST_DATABASE_URL="postgresql://saturday:saturday@127.0.0.1:5432/saturday_test_${nome}"

cd apps/core
if [ $# -gt 0 ]; then
  exec uv run pytest -q "$@"
fi
uv run ruff check --fix
uv run ruff format
uv run mypy
(cd ../../simuladores && uv run ruff check && uv run ruff format --check && uv run mypy)
uv run pytest -q
