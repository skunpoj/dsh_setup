#!/usr/bin/env bash
# Source-only guard. Reads one bounded commit-message file; never Docker/network/app writes.
set -euo pipefail
if [ "$#" -lt 1 ] || [ "$#" -gt 4 ] || [ ! -f "$1" ] || [ -L "$1" ]; then
  printf '%s\n' 'Expected one regular commit-message file and optional reason/force/branch arguments' >&2; exit 1
fi
size=$(wc -c < "$1")
if [ "$size" -gt 65536 ]; then printf '%s\n' 'Commit-message bound exceeded' >&2; exit 1; fi
reason=${2:-CI}
force=${3:-false}
branch=${4:-}
case "$force" in true|True|TRUE) force=true ;; false|False|FALSE) force=false ;; *) printf '%s\n' 'Force flag must be true or false' >&2; exit 1 ;; esac
if [ "$reason" = Manual ] && [ "$force" = true ] && [ "$branch" = refs/heads/main ]; then
  printf '%s\n' true
  exit 0
fi
if LC_ALL=C grep -Eiq '\[(skip ci|ci skip|skip azurepipelines|azurepipelines skip)\]' "$1"; then
  printf '%s\n' false
else
  printf '%s\n' true
fi
