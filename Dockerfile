FROM node:22-bookworm-slim

ARG DSH_VERSION=0.2.0-rc.2
ARG TTYD_VERSION=1.7.7

RUN apt-get update \
 && apt-get install -y --no-install-recommends bash ca-certificates curl git jq openssl procps python3 python3-pip python3-venv socat \
 && npm install -g --ignore-scripts "@deepseek-ai/dsh@${DSH_VERSION}" \
 && curl -fsSL -o /usr/local/bin/ttyd "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.x86_64" \
 && chmod 0755 /usr/local/bin/ttyd \
 && rm -rf /var/lib/apt/lists/* /root/.npm

COPY scripts/ /opt/dsh/scripts/
COPY container/start-dsh.sh /usr/local/bin/start-dsh
RUN chmod 0755 /usr/local/bin/start-dsh

EXPOSE 3081 7681
ENTRYPOINT ["/usr/local/bin/start-dsh"]
