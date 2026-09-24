# Multi-stage production container for DeepSeek Harness (DSH)
# Features: Multi-User Session Isolation, Web Login Gateway & LiteLLM Adapter

FROM node:22-alpine

LABEL description="DeepSeek Harness (DSH) with Multi-User Authentication & LiteLLM Gateway Adapter"

WORKDIR /app

# Install runtime dependencies
RUN apk add --no-cache git curl bash jq ca-certificates

# Install DSH globally
RUN npm install -g --ignore-scripts @deepseek-ai/dsh@0.1.5-rc.3

# Prepare workspace & configuration directories
RUN mkdir -p /workspace/users /workspace/repos /root/.dsh /scripts

# Copy scripts and configuration files
COPY scripts/ /scripts/
COPY cordis_plugin/ /app/cordis_plugin/

# Set file execution permissions
RUN chmod +x /scripts/*.js /scripts/*.sh 2>/dev/null || true

# Default environment configuration
ENV PORT=3080 \
    DSH_PORT=3081 \
    NODE_ENV=production \
    WORKSPACE_ROOT=/workspace/users

EXPOSE 3080 3081

ENTRYPOINT ["/bin/sh", "-c"]
CMD ["node /scripts/auth_proxy.js & node --expose-internals /usr/local/bin/dsh web --port 3081 --no-open"]
