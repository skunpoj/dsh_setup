#!/usr/bin/env bash
# Same source/header paths as preparation; no network, credentials or Docker socket.
set -euo pipefail
addon=$(cat /work/out/addon-path.txt)
case "$addon" in /work/source/*/node_modules/node-pty) ;; *) exit 65 ;; esac
test "$(realpath "$addon")" = "$addon"
cd "$addon"
test -f build/Makefile
# Only derived objects in this invocation's isolated source tree are removed.
rm -rf -- build/Release
make -C build -j2 BUILDTYPE=Release
test -f build/Release/pty.node
readelf --version-info build/Release/pty.node > /work/out/node-pty-glibc.txt
maximum=$(sed -n 's/.*Name: GLIBC_\([0-9.]*\).*/\1/p' /work/out/node-pty-glibc.txt | sort -V | tail -1)
test -n "$maximum"
test "$(printf '%s\n' "$maximum" 2.28 | sort -V | tail -1)" = 2.28
