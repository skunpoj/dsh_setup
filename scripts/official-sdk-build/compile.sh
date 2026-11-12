#!/usr/bin/env bash
# Every dependency must already be present in the admitted cache/image.
set -euo pipefail
cd /work/source
export HOME=/work/home CI=true COREPACK_ENABLE_NETWORK=0
export DSH_BUILD_CLIENT_PROFILE=official DSH_TELEMETRY_DISABLED=1
export PKG_CACHE_PATH=/deps/pkg-cache
export UV_OFFLINE=1 UV_NO_INDEX=1 UV_FIND_LINKS=/deps/python-wheels UV_PYTHON_DOWNLOADS=never
pnpm exec tsx scripts/build-exe-for-python-sdk.ts --targets=node24-linux-x64
python3 scripts/build-python-release.py --package sdk --output-dir /work/out/wheels
python3 scripts/build-python-release.py --package runtime --platform linux-x64 \
  --runtime-exe /work/source/dist-exe/deepseek-harness-sdk-runtime-linux-x64 \
  --output-dir /work/out/wheels
python3 -m venv /work/home/installed-smoke
smoke=/work/home/installed-smoke/bin/python
"$smoke" -m pip install --no-index --find-links /deps/python-wheels \
  /work/out/wheels/deepseek_harness_sdk-0.2.2a2-py3-none-any.whl \
  /work/out/wheels/deepseek_harness_runtime_bin-0.2.2a2-py3-none-manylinux_2_28_x86_64.whl
"$smoke" -m pip check
mkdir -p /work/out/smoke
cd /work/out/smoke
env -u PYTHONPATH -u DSH_RUNTIME_MODE "$smoke" /work/source/scripts/smoke-python-runtime.py --scenario sdk-default --installed-wheel
env -u PYTHONPATH -u DSH_RUNTIME_MODE "$smoke" /work/source/scripts/smoke-python-runtime.py --scenario sdk-mcp --installed-wheel
env -u PYTHONPATH -u DSH_RUNTIME_MODE "$smoke" /producer/keyless_approval.py
