FROM node:22-bookworm-slim

ARG DSH_VERSION=0.2.0-rc.2
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends bash ca-certificates curl git jq krb5-user openssl procps python3 python3-pip python3-venv socat \
 && npm install -g --ignore-scripts "@deepseek-ai/dsh@${DSH_VERSION}" \
 && rm -rf /var/lib/apt/lists/* /root/.npm

COPY vendor/ttyd /usr/local/bin/ttyd
RUN chmod 0755 /usr/local/bin/ttyd \
 && echo "8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55  /usr/local/bin/ttyd" | sha256sum -c -

RUN groupadd --gid 10001 dsh \
 && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/dsh dsh

ENV HOME=/home/dsh DSH_HOME=/home/dsh/.dsh KRB5CCNAME=FILE:/state/kerberos/ccache DSH_CONTEXT_TOKENS=1048576

COPY scripts/ /opt/dsh/scripts/
COPY tests/ /opt/dsh/tests/
COPY container/ /opt/dsh/container/
RUN node /opt/dsh/scripts/verify_upstream_contract.js \
 && node /opt/dsh/scripts/configure_models.js \
 && node /opt/dsh/scripts/verify_installed_candidate.js "${DSH_VERSION}" \
 && mkdir -p /opt/dsh/seed \
 && cp -a /home/dsh/.dsh /opt/dsh/seed/dsh-home \
 && install -m 0755 /opt/dsh/container/start-dsh.sh /usr/local/bin/start-dsh \
 && install -m 0755 /opt/dsh/container/prepare-offline-deps.sh /usr/local/bin/prepare-offline-deps \
 && chmod 0755 /opt/dsh/container/promote-packages.sh \
 && chown -R 10001:10001 /home/dsh /opt/dsh/seed/dsh-home

EXPOSE 3081 7681
ENTRYPOINT ["/usr/local/bin/start-dsh"]
