#!/usr/bin/env bash
set -euo pipefail

: "${DSH_ENVIRONMENT:?DSH_ENVIRONMENT must be secure or internet}"
: "${DSH_TRUSTED_HOST:?DSH_TRUSTED_HOST is required}"

case "$DSH_ENVIRONMENT" in
  secure|internet) ;;
  *) echo "invalid DSH_ENVIRONMENT=$DSH_ENVIRONMENT" >&2; exit 64 ;;
esac

mkdir -p /state/sessions /state/storages /state/attachments /workspace /runtime-tokens
rm -rf /root/.dsh
ln -s /state /root/.dsh

node /opt/dsh/scripts/configure_models.js

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
