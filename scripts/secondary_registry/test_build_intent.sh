#!/usr/bin/env bash
set -euo pipefail
root=$(mktemp -d /tmp/dsh-ci-intent-test.XXXXXXXX)
cleanup() {
  case "$root" in /tmp/dsh-ci-intent-test.*) rm -f -- "$root/message" "$root/large"; rmdir -- "$root";; *) exit 1;; esac
}
trap cleanup EXIT
script="$(cd "$(dirname "$0")" && pwd)/build-intent.sh"
check() { printf '%s' "$1" > "$root/message"; actual=$(bash "$script" "$root/message" "$2" "$3" "$4"); test "$actual" = "$5"; }
check 'Ordinary application or test change' IndividualCI false refs/heads/main true
check 'Source package [skip ci]' IndividualCI false refs/heads/main false
check 'Explicit [CI SKIP]' IndividualCI false refs/heads/main false
check 'Operator [skip azurepipelines]' IndividualCI false refs/heads/main false
check 'Operator [azurepipelines skip]' IndividualCI false refs/heads/main false
check 'Unrecognized skipci prose' IndividualCI false refs/heads/main true
check '' IndividualCI false refs/heads/main true
check 'Source package [skip ci]' Manual false refs/heads/main false
check 'Source package [skip ci]' Manual true refs/heads/main true
check 'Ordinary manual run' Manual true refs/heads/main true
check 'Source package [skip ci]' Manual true refs/heads/fix/test false
check 'Source package [skip ci]' Manual true '' false
check 'Source package [skip ci]' Schedule true refs/heads/main false
check 'Source package [skip ci]' PullRequest true refs/heads/main false
printf '%s' 'message' > "$root/message"
if bash "$script" "$root/message" Manual maybe refs/heads/main >/dev/null 2>&1; then exit 1; fi
if bash "$script" "$root/absent" Manual false refs/heads/main >/dev/null 2>&1; then exit 1; fi
head -c 65537 /dev/zero > "$root/large"
if bash "$script" "$root/large" Manual true refs/heads/main >/dev/null 2>&1; then exit 1; fi
printf '%s\n' '14 build-intent cases and 3 refusal checks passed; no Docker, network, build or deployment'
