#!/bin/sh
set -eu

# O bind mount ./data pode ser criado pelo Docker como root. Ajusta a
# permissão do diretório de checkpoints antes de executar a aplicação sem
# privilégios. Em alguns drivers de volume (ex.: Docker Desktop) o chown não
# é permitido; nesse caso seguimos e a aplicação reporta o erro com o caminho.
if [ "$(id -u)" = "0" ]; then
    checkpoint_path="${SATURDAY_CHECKPOINT_PATH:-/app/data/checkpoints.sqlite}"
    checkpoint_dir="$(dirname "$checkpoint_path")"
    mkdir -p "$checkpoint_dir" 2>/dev/null || true
    chown -R saturday:saturday "$checkpoint_dir" 2>/dev/null || true
    chmod u+rwx "$checkpoint_dir" 2>/dev/null || true
    exec gosu saturday "$@"
fi

exec "$@"
