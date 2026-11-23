#!/usr/bin/env bash
# Leva o ramo de uma worktree para a main e limpa o que era dela.
#
#   infra/worktree_entregar.sh <nome>
#
# Rode da raiz do checkout principal, na main, com tudo da worktree já em
# commit. Só fast-forward: se a main andou, o script faz o rebase na worktree e
# roda o infra/worktree_testar.sh antes. O push dispara o CI e o deploy do dev;
# o script espera o CI.
set -euo pipefail

nome="${1:?uso: infra/worktree_entregar.sh <nome>}"
caminho=".claude/worktrees/${nome}"
# O ramo é o da própria worktree: `worktree-<nome>` pelo `claude --worktree`,
# `claude/<nome>` pelo app.
ramo="$(git -C "$caminho" branch --show-current)"
[ -n "$ramo" ] || { echo "a worktree ${caminho} não está num ramo" >&2; exit 1; }

[ "$(git branch --show-current)" = "main" ] || { echo "rode na main" >&2; exit 1; }
sem_commit() {
  [ -z "$(git -C "$caminho" status --porcelain)" ] || { echo "a worktree tem mudança sem commit" >&2; exit 1; }
}
sem_commit

git fetch -q origin
# Outra sessão entregou no meio: a main local alcança a remota, o ramo vai para
# cima dela e as checagens rodam de novo antes do push.
git merge -q --ff-only origin/main
if ! git merge-base --is-ancestor main "$ramo"; then
  git -C "$caminho" rebase -q main || {
    echo "conflito no rebase: resolva na worktree e rode de novo" >&2
    exit 1
  }
  (cd "$caminho" && infra/worktree_testar.sh)
  sem_commit
fi
# Antes de mexer em qualquer coisa: a main local e a remota têm de estar no ramo.
for base in main origin/main; do
  git merge-base --is-ancestor "$base" "$ramo" || {
    echo "a ${base} andou: rode 'git rebase main' na worktree (depois de 'git pull --ff-only' aqui, se foi a origin) e os testes de novo" >&2
    exit 1
  }
done
git merge --ff-only "$ramo"
git push origin main
git worktree remove --force "$caminho"
git branch -d "$ramo"
docker exec saturday-postgres-1 dropdb -U saturday --if-exists "saturday_test_${nome}"

# O run leva alguns segundos para aparecer na lista.
sleep 15
run="$(gh run list --branch main --limit 1 --json databaseId --jq '.[0].databaseId')"
gh run watch "$run" --exit-status --interval 20 >/dev/null
gh run view "$run" --json conclusion,headSha --jq '"CI \(.conclusion) \(.headSha[0:7])"'
