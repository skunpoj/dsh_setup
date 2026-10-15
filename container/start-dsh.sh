#!/usr/bin/env bash
set -euo pipefail

: "${DSH_ENVIRONMENT:?DSH_ENVIRONMENT must be secure or internet}"
: "${DSH_TRUSTED_HOST:?DSH_TRUSTED_HOST is required}"

case "$DSH_ENVIRONMENT" in
  secure|internet) ;;
  *) echo "invalid DSH_ENVIRONMENT=$DSH_ENVIRONMENT" >&2; exit 64 ;;
esac

if [ "$DSH_ENVIRONMENT" = secure ]; then
  # Secure sessions resolve dependencies only from artifacts that an operator
  # has hash-approved and promoted from the Internet pool.
  export PIP_NO_INDEX=1
  export PIP_FIND_LINKS=/packages/approved/python
  export npm_config_offline=true
  export npm_config_cache=/packages/approved/npm-cache
else
  # Internet sessions may download packages, but can write only to incoming.
  # They never mount the approved cache or the protected workspace.
  export npm_config_cache=/packages/incoming/npm-cache
fi

mkdir -p /state/sessions /state/storages /state/attachments /workspace /runtime-tokens
rm -rf "${DSH_HOME:-$HOME/.dsh}"
ln -s /state "${DSH_HOME:-$HOME/.dsh}"
if [ ! -f /state/settings.yaml ]; then
  cp -a /opt/dsh/seed/dsh-home/. /state/
fi

ttyd -p 7681 -i 0.0.0.0 -W bash -l >/tmp/ttyd.log 2>&1 &

pod_ip="$(hostname -i | awk '{print $1}')"
fifo=/tmp/dsh-fifo
rm -f "$fifo"
mkfifo "$fifo"
dsh web --host "$pod_ip" --port 3081 --no-open --trusted-host "$DSH_TRUSTED_HOST" >"$fifo" 2>&1 &
dsh_pid=$!

while IFS= read -r line; do
  printf '%s\n' "$line"
  if [[ "$line" =~ token=([A-Za-z0-9_-]+) ]]; then
    umask 077
    printf '%s' "${BASH_REMATCH[1]}" >"/runtime-tokens/${DSH_ENVIRONMENT}"
  fi
done <"$fifo" &

cleanup() {
  kill "$dsh_pid" 2>/dev/null || true
  wait "$dsh_pid" 2>/dev/null || true
}
trap cleanup TERM INT
wait "$dsh_pid"
