# Multi-stage production container for DeepSeek Harness (DSH)
# Features: Multi-User Session Isolation, Web Login Gateway & LiteLLM Adapter

FROM ubuntu:24.04

LABEL description="DeepSeek Harness (DSH) on Ubuntu 24.04 with Multi-User Authentication, Python 3.12, ttyd & LiteLLM Gateway Adapter"

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Bangkok \
    PORT=3080 \
    DSH_PORT=3081 \
    NODE_ENV=production \
    WORKSPACE_ROOT=/workspace/users

WORKDIR /app

# Install base dependencies, build tools and Python 3.12 runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    bash \
    jq \
    ca-certificates \
    python3 \
    python3-pip \
    python3-venv \
    python-is-python3 \
    build-essential \
    socat \
    openssl \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 22 LTS via NodeSource
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install ttyd web terminal
RUN curl -fsSL -o /usr/local/bin/ttyd https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64 \
    && chmod +x /usr/local/bin/ttyd

# Install DSH globally
RUN npm install -g --ignore-scripts @deepseek-ai/dsh@0.1.5-rc.3

# Prepare workspace & configuration directories
RUN mkdir -p /workspace/users /workspace/repos /root/.dsh /scripts

# Copy scripts and configuration files
COPY scripts/ /scripts/
COPY cordis_plugin/ /app/cordis_plugin/

# Set file execution permissions
RUN chmod +x /scripts/*.js /scripts/*.sh 2>/dev/null || true

EXPOSE 3080 3081

ENTRYPOINT ["/bin/sh", "-c"]
CMD ["node /scripts/auth_proxy.js & node --expose-internals /usr/local/bin/dsh web --port 3081 --no-open"]
