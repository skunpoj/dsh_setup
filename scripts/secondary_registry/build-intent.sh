#!/usr/bin/env bash
# Source-only guard. Reads one bounded commit-message file; never Docker/network/app writes.
set -euo pipefail
if [ "$#" -ne 1 ] || [ ! -f "$1" ] || [ -L "$1" ]; then
  printf '%s\n' 'Expected one regular commit-message file' >&2; exit 1
fi
size=$(wc -c < "$1")
if [ "$size" -gt 65536 ]; then printf '%s\n' 'Commit-message bound exceeded' >&2; exit 1; fi
if LC_ALL=C grep -Eiq '\[(skip ci|ci skip|skip azurepipelines|azurepipelines skip)\]' "$1"; then
  printf '%s\n' 'false'
else
  printf '%s\n' 'true'
fi
