#!/usr/bin/env bash
# Invoked only inside the admitted Linux builder with --network none.
set -euo pipefail
cd /work/source
export HOME=/work/home
export CI=true COREPACK_ENABLE_NETWORK=0 DSH_TELEMETRY_DISABLED=1
export npm_config_nodedir="/work/home/.cache/node-gyp/$(node --version | sed 's/^v//')"
mkdir -p /work/out /work/home/.cache /work/home/pnpm-store
cp -a /deps/node-gyp /work/home/.cache/
cp -a /deps/pnpm-store/. /work/home/pnpm-store/
test -f "$npm_config_nodedir/include/node/node.h"
node_version=$(node --version)
pnpm_version=$(pnpm --version)
uv_version=$(uv --version | awk '{print $2}')
export node_version pnpm_version uv_version
python3 - <<'PY'
import json,os,re
node=os.environ['node_version']; match=re.fullmatch(r'v24\.(\d+)\.(\d+)',node)
assert match and int(match[1])>=9, 'SDK requires the reviewed Node24 toolchain'
assert os.environ['pnpm_version']=='11.28.5'
assert os.environ['uv_version']=='0.11.23'
with open('/work/out/tools.json','x') as f:
    json.dump({'nodeVersion':node,'pnpmVersion':os.environ['pnpm_version'],
               'uvVersion':os.environ['uv_version']},f)
PY
pnpm install --frozen-lockfile --offline --store-dir /work/home/pnpm-store
addon=$(realpath packages/subprocess/subprocess-local/node_modules/node-pty)
case "$addon" in /work/source/*/node_modules/node-pty) ;; *) exit 65 ;; esac
(cd "$addon" && npm_config_build_from_source=true pnpm --config.verifyDepsBeforeRun=false run install)
test -f "$addon/build/Makefile"
printf '%s\n' "$addon" > /work/out/addon-path.txt
