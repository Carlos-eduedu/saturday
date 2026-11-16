#!/usr/bin/env bash
# Leva o ramo de uma worktree para a main e limpa o que era dela.
#
#   infra/worktree_entregar.sh <nome>
#
# Rode da raiz do checkout principal, na main, com tudo da worktree já em
# commit. Só fast-forward: se a main andou, faça `git rebase main` na worktree
# antes. O push dispara o CI e o deploy do dev; o script espera o CI.
set -euo pipefail

nome="${1:?uso: infra/worktree_entregar.sh <nome>}"
caminho=".claude/worktrees/${nome}"

[ "$(git branch --show-current)" = "main" ] || { echo "rode na main" >&2; exit 1; }
[ -z "$(git -C "$caminho" status --porcelain)" ] || { echo "a worktree tem mudança sem commit" >&2; exit 1; }

git fetch -q origin
git merge --ff-only "worktree-${nome}"
git push origin main
git worktree remove --force "$caminho"
git branch -d "worktree-${nome}"
docker exec saturday-postgres-1 dropdb -U saturday --if-exists "saturday_test_${nome}"

# O run leva alguns segundos para aparecer na lista.
sleep 15
run="$(gh run list --branch main --limit 1 --json databaseId --jq '.[0].databaseId')"
gh run watch "$run" --exit-status --interval 20 >/dev/null
gh run view "$run" --json conclusion,headSha --jq '"CI \(.conclusion) \(.headSha[0:7])"'
