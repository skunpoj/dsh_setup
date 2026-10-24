#!/usr/bin/env bash
set -euo pipefail
root=$(mktemp -d /tmp/dsh-ci-intent-test.XXXXXXXX)
cleanup() {
  case "$root" in /tmp/dsh-ci-intent-test.*) rm -f -- "$root/message" "$root/large"; rmdir -- "$root";; *) exit 1;; esac
}
trap cleanup EXIT
script="$(cd "$(dirname "$0")" && pwd)/build-intent.sh"
check() { printf '%s' "$1" > "$root/message"; actual=$(bash "$script" "$root/message"); test "$actual" = "$2"; }
check 'Ordinary application or test change' true
check 'Source package [skip ci]' false
check 'Explicit [CI SKIP]' false
check 'Operator [skip azurepipelines]' false
check 'Operator [azurepipelines skip]' false
check 'Unrecognized skipci prose' true
check '' true
if bash "$script" "$root/absent" >/dev/null 2>&1; then exit 1; fi
head -c 65537 /dev/zero > "$root/large"
if bash "$script" "$root/large" >/dev/null 2>&1; then exit 1; fi
printf '%s\n' '9 CI intent guards passed; no Docker, network, build or deployment'
