#!/usr/bin/env bash
set -euo pipefail

incoming="${INCOMING_ROOT:-/packages/incoming}"
kind="${1:-}"
source_path="${2:-}"

case "$kind" in
  python)
    [ -f "$source_path" ] || { echo "requirements file not found" >&2; exit 64; }
    mkdir -p "$incoming/python"
    python3 -m pip download --requirement "$source_path" --dest "$incoming/python"
    ;;
  npm)
    [ -d "$source_path" ] || { echo "project directory not found" >&2; exit 64; }
    [ -f "$source_path/package-lock.json" ] || { echo "package-lock.json is required" >&2; exit 64; }
    mkdir -p "$incoming/npm-cache"
    (cd "$source_path" && npm ci --ignore-scripts --cache "$incoming/npm-cache")
    ;;
  *)
    echo "usage: prepare-offline-deps python <requirements.txt> | npm <project-directory>" >&2
    exit 64
    ;;
esac

echo "dependency artifacts downloaded into $incoming; generate SHA-256 rows for operator review before promotion"
