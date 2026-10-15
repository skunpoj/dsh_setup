FROM node:22-bookworm-slim

ARG DSH_VERSION=0.2.0-rc.2
ARG TTYD_VERSION=1.7.7

RUN apt-get update \
 && apt-get install -y --no-install-recommends bash ca-certificates curl git jq openssl procps python3 python3-pip python3-venv socat \
 && npm install -g --ignore-scripts "@deepseek-ai/dsh@${DSH_VERSION}" \
 && curl -fsSL -o /usr/local/bin/ttyd "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.x86_64" \
 && chmod 0755 /usr/local/bin/ttyd \
 && rm -rf /var/lib/apt/lists/* /root/.npm

RUN groupadd --gid 10001 dsh \
 && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/dsh dsh

ENV HOME=/home/dsh DSH_HOME=/home/dsh/.dsh

COPY scripts/ /opt/dsh/scripts/
COPY container/ /opt/dsh/container/
RUN node /opt/dsh/scripts/configure_models.js \
 && mkdir -p /opt/dsh/seed \
 && cp -a /home/dsh/.dsh /opt/dsh/seed/dsh-home \
 && install -m 0755 /opt/dsh/container/start-dsh.sh /usr/local/bin/start-dsh \
 && install -m 0755 /opt/dsh/container/prepare-offline-deps.sh /usr/local/bin/prepare-offline-deps \
 && chmod 0755 /opt/dsh/container/promote-packages.sh \
 && chown -R 10001:10001 /home/dsh /opt/dsh/seed/dsh-home

EXPOSE 3081 7681
ENTRYPOINT ["/usr/local/bin/start-dsh"]
