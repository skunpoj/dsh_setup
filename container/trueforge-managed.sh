#!/bin/sh
set -eu
# A separate private database preserves DSH's existing sessions and configuration.
export HOST=127.0.0.1 PORT=8790 STANDALONE=true
export XDG_DATA_HOME=/state/trueforge
export MODEL_CATALOG_PATH=/opt/dsh/container/trueforge-model-catalog.yaml
export OTEL_SDK_DISABLED=true
unset NODE_TLS_REJECT_UNAUTHORIZED
exec node /usr/local/lib/node_modules/@truefoundry/trueforge/dist/cli.js "$@"
