FROM node:22-bookworm-slim

ARG DSH_VERSION=0.2.2-rc.1
ARG PI_AI_VERSION=1.3.0
ARG CLAUDE_CODE_VERSION=2.1.301
ARG TRUEFORGE_VERSION=0.179.2
ARG KILO_VERSION=7.8.12
ARG JUPYTERLAB_VERSION=4.6.4
ARG JUPYTER_SERVER_VERSION=2.21.1
ARG IPYKERNEL_VERSION=7.4.0
# Operator/rendering helpers use system Python, outside the Jupyter virtualenv.
ARG PYTHON3_YAML_DEB_VERSION=6.0-3+b2
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends bash ca-certificates curl git jq krb5-user openssl procps python3 python3-pip python3-venv "python3-yaml=${PYTHON3_YAML_DEB_VERSION}" socat \
 && python3 -c 'import yaml; assert yaml.safe_load("enabled: true") == {"enabled": True}' \
 && npm install -g --ignore-scripts "@deepseek-ai/dsh@${DSH_VERSION}" \
 && npm install --prefix /usr/local/lib/node_modules/@deepseek-ai/dsh --no-save --omit=dev --ignore-scripts --package-lock=false "@earendil-works/pi-ai@${PI_AI_VERSION}" \
 && npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" "@truefoundry/trueforge@${TRUEFORGE_VERSION}" \
 && npm install -g "@kilocode/cli@${KILO_VERSION}" \
 && rm -rf /var/lib/apt/lists/* /root/.npm

# Install at image build time; offline runtimes never bootstrap from PyPI.
RUN python3 -m venv /opt/dsh/jupyter \
 && /opt/dsh/jupyter/bin/python -m pip install --no-cache-dir \
      "jupyterlab==${JUPYTERLAB_VERSION}" "jupyter-server==${JUPYTER_SERVER_VERSION}" "ipykernel==${IPYKERNEL_VERSION}"

COPY vendor/ttyd /usr/local/bin/ttyd
RUN chmod 0755 /usr/local/bin/ttyd \
 && echo "8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55  /usr/local/bin/ttyd" | sha256sum -c -

RUN groupadd --gid 10001 dsh \
 && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/dsh dsh

ENV HOME=/home/dsh DSH_HOME=/home/dsh/.dsh KRB5CCNAME=FILE:/state/kerberos/ccache DSH_CONTEXT_TOKENS=1048576 PYTHONPATH=/opt/dsh

COPY vendor/ldapts/ /opt/dsh/vendor/ldapts/
RUN echo "addd5d000792577dff58be59a3314e8efe570689989df6c3f085c8d28efd3f1c  /opt/dsh/vendor/ldapts/ldapts.cjs" | sha256sum -c -
COPY scripts/ /opt/dsh/scripts/
COPY config/ /opt/dsh/config/
COPY tests/ /opt/dsh/tests/
RUN node --test /opt/dsh/tests/test_ldap_auth.cjs /opt/dsh/tests/test_identity_auth.cjs /opt/dsh/tests/test_ldap_gateway.cjs
COPY patches/ /opt/dsh/patches/
COPY container/ /opt/dsh/container/
RUN install -m 0755 /opt/dsh/container/dsh-unattended.py /usr/local/bin/dsh-unattended \
 && install -m 0755 /opt/dsh/container/dsh-task-broker.py /usr/local/bin/dsh-task-broker \
 && install -m 0755 /opt/dsh/container/dsh-openshell-worker.py /usr/local/bin/dsh-openshell-worker \
 && install -m 0755 /opt/dsh/container/dsh-sdk-task.py /usr/local/bin/dsh-sdk-task \
 && install -m 0755 /opt/dsh/container/dsh-official-sdk-runtime.py /usr/local/bin/dsh-official-sdk-runtime \
 && PYTHONPATH=/opt/dsh python3 -m unittest discover -s /opt/dsh/tests -p test_unattended_model_guard.py \
 && PYTHONPATH=/opt/dsh python3 -m unittest discover -s /opt/dsh/tests -p test_unattended_launcher.py \
 && PYTHONPATH=/opt/dsh python3 -m unittest discover -s /opt/dsh/tests -p test_task_broker.py \
 && PYTHONPATH=/opt/dsh python3 -m unittest discover -s /opt/dsh/tests -p test_official_sdk_approval.py \
 && PYTHONPATH=/opt/dsh python3 -m unittest discover -s /opt/dsh/tests -p test_official_sdk_session.py \
 && PYTHONPATH=/opt/dsh python3 -m unittest discover -s /opt/dsh/tests -p test_official_sdk_release_admission.py \
 && PYTHONPATH=/opt/dsh python3 -m unittest discover -s /opt/dsh/tests -p test_official_sdk_runtime_entry.py \
 && PYTHONPATH=/opt/dsh python3 -m unittest discover -s /opt/dsh/tests -p test_official_sdk_task.py \
 && PYTHONPATH=/opt/dsh python3 -m unittest discover -s /opt/dsh/tests -p test_official_sdk_isolation.py \
 && PYTHONPATH=/opt/dsh python3 -m unittest discover -s /opt/dsh/tests -p test_official_sdk_bootstrap.py \
 && PYTHONPATH=/opt/dsh python3 -m unittest discover -s /opt/dsh/tests -p test_official_sdk_deployment_observer.py \
 && PYTHONPATH=/opt/dsh python3 -m unittest discover -s /opt/dsh/tests -p test_official_sdk_test_api.py \
 && PYTHONPATH=/opt/dsh python3 -m unittest discover -s /opt/dsh/tests -p test_official_sdk_executing_identity.py \
 && PYTHONPATH=/opt/dsh python3 -m unittest discover -s /opt/dsh/tests -p test_openshell_task_binding.py \
 && PYTHONPATH=/opt/dsh python3 -m unittest discover -s /opt/dsh/tests -p test_openshell_broker_service.py \
 && PYTHONPATH=/opt/dsh python3 -m unittest discover -s /opt/dsh/tests -p test_openshell_worker_execution.py \
 && PYTHONPATH=/opt/dsh python3 -m unittest discover -s /opt/dsh/tests -p test_openshell_native_rpc.py \
 && PYTHONPATH=/opt/dsh python3 -m unittest discover -s /opt/dsh/tests -p test_openshell_broker_transport.py \
 && PYTHONPATH=/opt/dsh python3 -m unittest discover -s /opt/dsh/tests -p test_openshell_bootstrap.py \
 && PYTHONPATH=/opt/dsh python3 -m unittest discover -s /opt/dsh/tests -p test_openshell_worker_entry.py \
 && PYTHONPATH=/opt/dsh python3 -m unittest tests.test_openshell_kubernetes_identity tests.test_openshell_kubernetes_observer tests.test_openshell_kubernetes_api tests.test_openshell_kubernetes_retirement \
 && node /opt/dsh/tests/test_agent_task_gateway.cjs \
 && node /opt/dsh/tests/test_native_sdk_approval_ui.cjs
RUN node /opt/dsh/tests/test_openshell_complete_worker.cjs
# Optional custom light theme ("Custom" beside native Light/Dark/System). start-dsh installs it into a
# workspace profile only when DSH_NATIVE_THEME_PLUGIN=1. The package is root-owned and read-only; the
# installer pins its client bundle, and its test runs as the unprivileged workspace user.
COPY plugins/dsh-theme-custom-light/ /opt/dsh/plugins/dsh-theme-custom-light/
RUN chown -R root:root /opt/dsh/plugins && chmod -R a-w,a+rX /opt/dsh/plugins \
 && echo "7002d9bebced3037c7d38f4ef342e5e6ffccbfc874bed8086b06eccd1480e88b  /opt/dsh/plugins/dsh-theme-custom-light/lib/client.js" | sha256sum -c - \
 && su -s /bin/sh -c 'node /opt/dsh/tests/test_native_theme_profile.cjs' dsh
RUN install -m 0755 /opt/dsh/container/jupyter-managed.py /usr/local/bin/jupyter \
 && ln -s /usr/local/bin/jupyter /usr/local/bin/jupyterlab \
 && su -s /bin/sh -c '/opt/dsh/jupyter/bin/python /opt/dsh/tests/test_managed_jupyter.py' dsh
RUN mkdir -p /etc/kilo /etc/dsh-kilo-config/kilo \
 && install -m 0644 /opt/dsh/container/kilo-managed.json /etc/kilo/kilo.json \
 && install -m 0755 /opt/dsh/container/kilo-managed.py /usr/local/bin/kilo-managed \
 && rm /usr/local/bin/kilo /usr/local/bin/kilocode \
 && ln -s /usr/local/bin/kilo-managed /usr/local/bin/kilo \
 && ln -s /usr/local/bin/kilo-managed /usr/local/bin/kilocode \
 && node /usr/local/lib/node_modules/@kilocode/cli/bin/kilo --version \
 && python3 -m unittest discover -s /opt/dsh/tests -p test_managed_kilo.py
RUN node /opt/dsh/tests/test_release_dependencies.js \
 && node /opt/dsh/tests/test_upgrade_runtime_profile.js \
 && node /opt/dsh/tests/test_session_archive.mjs \
 && node /opt/dsh/scripts/verify_release_dependencies.js "${DSH_VERSION}" "${PI_AI_VERSION}" \
 && python3 /opt/dsh/scripts/configure_managed_harnesses.py \
 && python3 /opt/dsh/scripts/configure_platform_guide.py --image \
 && python3 /opt/dsh/scripts/configure_workspace_tools.py \
 && python3 -m unittest discover -s /opt/dsh/tests -p test_workspace_file_tools.py \
 && node /opt/dsh/tests/test_managed_harnesses.mjs \
 && node /opt/dsh/tests/test_managed_inference_transport.js \
 && node /opt/dsh/tests/test_managed_budget.js \
 && node /opt/dsh/tests/test_managed_budget_loader.js \
 && DSH_MANAGED_TRANSPORT=1 NODE_OPTIONS='--require /opt/dsh/scripts/managed_inference_transport.cjs' node /opt/dsh/tests/test_managed_budget_hook.mjs \
 && node /opt/dsh/tests/test_managed_compaction_quality.cjs \
 && node /opt/dsh/scripts/verify_upstream_contract.js \
 && node /opt/dsh/tests/test_prompt_admission_diagnostics.mjs \
 && node /opt/dsh/scripts/configure_models.js \
 && node /opt/dsh/scripts/configure_image_model_lookup.mjs \
 && node /opt/dsh/tests/test_image_model_lookup.mjs \
 && python3 /opt/dsh/scripts/configure_platform_guide.py --state /home/dsh/.dsh \
 && node /opt/dsh/scripts/verify_installed_candidate.js "${DSH_VERSION}" \
 && mkdir -p /opt/dsh/seed \
 && cp -a /home/dsh/.dsh /opt/dsh/seed/dsh-home \
 && install -m 0755 /opt/dsh/container/start-dsh.sh /usr/local/bin/start-dsh \
 && install -m 0755 /opt/dsh/container/prepare-offline-deps.sh /usr/local/bin/prepare-offline-deps \
 && chmod 0755 /opt/dsh/container/promote-packages.sh \
 && chown -R 10001:10001 /home/dsh /opt/dsh/seed/dsh-home

ARG KUBECTL_VERSION=v1.32.9
ARG KUBECTL_LINUX_AMD64_SHA256=509ae171bac7ad3b98cc49f5594d6bc84900cf6860f155968d1059fde3be5286
RUN curl --fail --location --silent --show-error --connect-timeout 15 --max-time 120 --retry 0 "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" --output /usr/local/bin/kubectl \
 && echo "${KUBECTL_LINUX_AMD64_SHA256}  /usr/local/bin/kubectl" | sha256sum -c - \
 && chmod 0755 /usr/local/bin/kubectl \
 && kubectl version --client=true --output=json | jq -e --arg version "${KUBECTL_VERSION#v}" '.clientVersion.gitVersion == ("v" + $version)' >/dev/null

EXPOSE 3081 7681 7682
ENTRYPOINT ["/usr/local/bin/start-dsh"]
