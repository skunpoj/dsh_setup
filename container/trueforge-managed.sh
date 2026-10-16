#!/bin/sh
set -eu
# A separate private database preserves DSH's existing sessions and configuration.
export HOST=127.0.0.1 PORT=8790 STANDALONE=true
export XDG_DATA_HOME=/state/trueforge
export MODEL_CATALOG_PATH=/opt/dsh/container/trueforge-model-catalog.yaml
export OTEL_SDK_DISABLED=true
export OUTBOUND_URL_ALLOWED_HOSTS='["litellm.llm.svc.cluster.local"]'
export OUTBOUND_HTTP_HEADERS_TIMEOUT_MS=3600000 OUTBOUND_HTTP_BODY_TIMEOUT_MS=3600000
unset NODE_TLS_REJECT_UNAUTHORIZED
exec node /usr/local/lib/node_modules/@truefoundry/trueforge/dist/cli.js "$@"
