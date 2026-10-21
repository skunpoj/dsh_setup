#!/bin/sh
set -eu
# A separate private database preserves DSH's existing sessions and configuration.
# Port 3000 is already behind the authenticated, per-user DSH app gateway.
export HOST=0.0.0.0 PORT=3000 STANDALONE=true
export XDG_DATA_HOME=/state/trueforge
export MODEL_CATALOG_PATH=/opt/dsh/container/trueforge-model-catalog.yaml
export OTEL_SDK_DISABLED=true
export OUTBOUND_URL_ALLOWED_HOSTS='["litellm"]'
export OUTBOUND_HTTP_HEADERS_TIMEOUT_MS=3600000 OUTBOUND_HTTP_BODY_TIMEOUT_MS=3600000
# Model transport has separate deadlines; generic outbound settings do not cover it.
export MODEL_HTTP_HEADERS_TIMEOUT_MS=3600000 MODEL_HTTP_BODY_TIMEOUT_MS=3600000
# A bounded admission response must not silently replay a long request.
export MODEL_HTTP_MAX_RETRIES=0
unset NODE_TLS_REJECT_UNAUTHORIZED
exec node /usr/local/lib/node_modules/@truefoundry/trueforge/dist/cli.js "$@"
