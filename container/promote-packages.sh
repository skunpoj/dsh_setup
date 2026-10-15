#!/usr/bin/env bash
set -euo pipefail

manifest="${APPROVAL_MANIFEST:-/approval/manifest.sha256}"
incoming="${INCOMING_ROOT:-/packages/incoming}"
approved="${APPROVED_ROOT:-/packages/approved}"

[ -f "$manifest" ] || { echo "approval manifest not found" >&2; exit 64; }
mkdir -p "$approved"
count=0

while read -r digest relative extra; do
  [ -z "${digest:-}" ] && continue
  case "$digest" in \#*) continue ;; esac
  [ -z "${extra:-}" ] || { echo "invalid manifest row: $digest $relative $extra" >&2; exit 65; }
  case "$relative" in
    /*|*..*) echo "unsafe artifact path: $relative" >&2; exit 65 ;;
  esac
  source_file="$incoming/$relative"
  [ -f "$source_file" ] || { echo "approved artifact missing: $relative" >&2; exit 66; }
  actual="$(sha256sum "$source_file" | awk '{print $1}')"
  [ "$actual" = "$digest" ] || { echo "hash mismatch: $relative" >&2; exit 67; }
  destination="$approved/$relative"
  mkdir -p "$(dirname "$destination")"
  install -m 0444 "$source_file" "$destination"
  count=$((count + 1))
done <"$manifest"

[ "$count" -gt 0 ] || { echo "approval manifest contains no artifacts" >&2; exit 68; }
echo "promoted $count verified dependency artifacts"
