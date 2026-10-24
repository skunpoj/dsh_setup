FROM node:22-bookworm-slim

ARG DSH_VERSION=0.2.0-rc.2
ARG CLAUDE_CODE_VERSION=2.1.301
ARG TRUEFORGE_VERSION=0.179.2
# Operator/rendering helpers use system Python, outside any Jupyter virtualenv.
ARG PYTHON3_YAML_DEB_VERSION=6.0-3+b2
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends bash ca-certificates curl git jq krb5-user openssl procps python3 python3-pip python3-venv "python3-yaml=${PYTHON3_YAML_DEB_VERSION}" socat \
 && python3 -c 'import yaml; assert yaml.safe_load("enabled: true") == {"enabled": True}' \
 && npm install -g --ignore-scripts "@deepseek-ai/dsh@${DSH_VERSION}" \
 && npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" "@truefoundry/trueforge@${TRUEFORGE_VERSION}" \
 && rm -rf /var/lib/apt/lists/* /root/.npm

COPY vendor/ttyd /usr/local/bin/ttyd
COPY vendor/ldapts/ /opt/dsh/vendor/ldapts/
RUN echo "addd5d000792577dff58be59a3314e8efe570689989df6c3f085c8d28efd3f1c  /opt/dsh/vendor/ldapts/ldapts.cjs" | sha256sum -c -
RUN chmod 0755 /usr/local/bin/ttyd \
 && echo "8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55  /usr/local/bin/ttyd" | sha256sum -c -

RUN groupadd --gid 10001 dsh \
 && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/dsh dsh

ENV HOME=/home/dsh DSH_HOME=/home/dsh/.dsh KRB5CCNAME=FILE:/state/kerberos/ccache DSH_CONTEXT_TOKENS=1048576

COPY scripts/ /opt/dsh/scripts/
COPY tests/ /opt/dsh/tests/
COPY container/ /opt/dsh/container/
RUN node --test /opt/dsh/tests/test_ldap_auth.cjs /opt/dsh/tests/test_identity_auth.cjs /opt/dsh/tests/test_ldap_gateway.cjs \
 && python3 /opt/dsh/scripts/configure_managed_harnesses.py \
 && node /opt/dsh/tests/test_managed_harnesses.mjs \
 && node /opt/dsh/tests/test_managed_inference_transport.js \
 && node /opt/dsh/tests/test_managed_budget.js \
 && DSH_MANAGED_TRANSPORT=1 NODE_OPTIONS='--require /opt/dsh/scripts/managed_inference_transport.cjs' node /opt/dsh/tests/test_managed_budget_hook.mjs \
 && node /opt/dsh/tests/test_managed_compaction_quality.cjs \
 && node /opt/dsh/scripts/verify_upstream_contract.js \
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
