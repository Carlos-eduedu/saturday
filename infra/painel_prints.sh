#!/usr/bin/env bash
# Prints do painel local para o relatório de antes e depois: para cada caminho,
# desktop claro, desktop escuro e celular.
#
#   PAINEL_LOCAL_SENHA=... infra/painel_prints.sh <pasta> <caminho>...
#   PAINEL_LOCAL_SENHA=... infra/painel_prints.sh /tmp/antes / /conversas/3
#
# Precisa do painel no ar (`infra/painel_local.sh seed`, com a mesma
# PAINEL_LOCAL_SENHA ou a senha que o seed imprimiu) e do `agent-browser`.
set -euo pipefail

[ $# -ge 2 ] || { echo "uso: $0 <pasta> <caminho>..." >&2; exit 2; }
: "${PAINEL_LOCAL_SENHA:?defina PAINEL_LOCAL_SENHA com a senha do gestor do seed}"
BASE="${PAINEL_LOCAL_URL:-http://localhost:5173}"
# Outra pessoa do seed (ex.: bia@exemplo.test): feche antes o navegador
# (`agent-browser close`), que guarda a sessão de quem entrou por último.
EMAIL="${PAINEL_LOCAL_EMAIL:-gestor@exemplo.test}"
pasta="$1"
shift
mkdir -p "$pasta"

agent-browser open "$BASE/login" >/dev/null
agent-browser wait 800 >/dev/null
# Sessão já aberta de uma rodada anterior pula o formulário.
if agent-browser fill 'input[type="email"]' "$EMAIL" >/dev/null 2>&1; then
  agent-browser fill 'input[type="password"]' "$PAINEL_LOCAL_SENHA" >/dev/null
  agent-browser press Enter >/dev/null
  agent-browser wait 1200 >/dev/null
fi

foto() { # <caminho> <sufixo> <largura> <altura> <tema>
  agent-browser set viewport "$3" "$4" >/dev/null
  agent-browser set media "$5" >/dev/null
  agent-browser open "$BASE$1" >/dev/null
  agent-browser wait 1500 >/dev/null
  agent-browser screenshot "$pasta/$nome-$2.png" >/dev/null
  echo "$pasta/$nome-$2.png"
}

for caminho in "$@"; do
  nome="$(printf '%s' "${caminho#/}" | tr '/?=&' '----')"
  nome="${nome:-inicio}"
  foto "$caminho" desktop-claro 1280 800 light
  foto "$caminho" desktop-escuro 1280 800 dark
  foto "$caminho" celular 390 844 light
done
