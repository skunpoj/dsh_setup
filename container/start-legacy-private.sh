#!/bin/bash
set -euo pipefail
umask 077
export HOME=/root DSH_HOME=/root/.dsh
mkdir -p "$HOME/.kerberos"
export KRB5CCNAME=FILE:/root/.kerberos/ccache
test "$(id -u)" = 10001
test -s /workspace/users/.user_auth.json
test -f /root/.legacy-migration-complete
fifo=/tmp/dsh-private-fifo
mkfifo "$fifo"
node /scripts/auth_proxy.js &
auth_pid=$!
ttyd -p 7681 -i 127.0.0.1 -W bash -l >/tmp/ttyd.log 2>&1 &
terminal_pid=$!
args=(web --host 127.0.0.1 --port 3081 --no-open --trusted-host "$DSH_TRUSTED_HOST")
IFS=',' read -ra aliases <<< "${DSH_TRUSTED_HOST_ALIASES:-}"
for host in "${aliases[@]}"; do
  if [[ -n "$host" ]]; then args+=(--trusted-host "$host"); fi
done
dsh "${args[@]}" >"$fifo" 2>&1 &
dsh_pid=$!
while IFS= read -r line; do
  if [[ "$line" =~ token=([A-Za-z0-9_-]+) ]]; then
    printf '%s' "${BASH_REMATCH[1]}" >/tmp/dsh_token.txt
  else
    printf '%s\n' "$line" >>/root/.dsh/startup-private.log
  fi
done <"$fifo" &
capture_pid=$!
cleanup() {
  kill "$dsh_pid" "$auth_pid" "$terminal_pid" "$capture_pid" 2>/dev/null || true
  wait "$dsh_pid" "$auth_pid" "$terminal_pid" "$capture_pid" 2>/dev/null || true
}
trap cleanup TERM INT EXIT
wait -n "$dsh_pid" "$auth_pid" "$terminal_pid"
