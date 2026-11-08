ARG PYTHON314_IMAGE
ARG DSH_BASE_IMAGE
FROM ${PYTHON314_IMAGE} AS managed_python
ARG PYTHON314_IMAGE
RUN case "$PYTHON314_IMAGE" in *@sha256:*) ;; *) exit 64;; esac
RUN python -c 'import sys; assert sys.version_info[:2] == (3,14)'
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 LANGSMITH_TRACING=false DO_NOT_TRACK=1
# A compiler exists only in this builder stage, for the one source distribution in the lock (forbiddenfruit 0.1.4).
# Nothing from this stage except the finished virtual environment reaches the final image.
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*
COPY config/deepagents-requirements.txt config/deepagents-requirements.lock.txt /build/
# Every distribution is pinned with hashes (--require-hashes). All are wheels except the single source distribution
# named below, which is built into a wheel here and then installed together with the downloaded ones.
RUN python3.14 -m venv /opt/dsh/deepagents \
 && /opt/dsh/deepagents/bin/python -m pip wheel --require-hashes --no-deps --only-binary=:all: --no-binary=forbiddenfruit \
      --wheel-dir /build/wheels -r /build/deepagents-requirements.lock.txt \
 && sed -n 's/^\([A-Za-z0-9_.-]*==[^ \\]*\).*/\1/p' /build/deepagents-requirements.lock.txt > /build/pinned.txt \
 && /opt/dsh/deepagents/bin/python -m pip install --no-index --no-deps --find-links /build/wheels -r /build/pinned.txt \
 && /opt/dsh/deepagents/bin/python -m pip check
RUN /opt/dsh/deepagents/bin/python -c 'import pathlib,hashlib,json; p=pathlib.Path("/build/wheels"); l=hashlib.sha256(pathlib.Path("/build/deepagents-requirements.lock.txt").read_bytes()).hexdigest(); print(json.dumps({"lock_sha256":l,"wheels":{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(p.glob("*.whl"))}},sort_keys=True))' > /build/WHEEL_SHA256.json
FROM ${DSH_BASE_IMAGE}
ARG DSH_BASE_IMAGE
USER root
ARG DSH_LITELLM_NAMESPACE
RUN test -n "$DSH_LITELLM_NAMESPACE" && case "$DSH_BASE_IMAGE" in *@sha256:*) ;; *) exit 64;; esac
COPY --from=managed_python /usr/local/bin/python3.14 /usr/local/bin/python3.14
COPY --from=managed_python /usr/local/lib/libpython3.14.so.1.0 /usr/local/lib/libpython3.14.so.1.0
COPY --from=managed_python /usr/local/lib/python3.14/ /usr/local/lib/python3.14/
COPY --from=managed_python /opt/dsh/deepagents/ /opt/dsh/deepagents/
COPY --from=managed_python /build/WHEEL_SHA256.json /opt/dsh/deepagents-WHEEL_SHA256.json
RUN ldconfig && /opt/dsh/deepagents/bin/python -c 'import sys; assert sys.version_info[:2] == (3,14)'
COPY container/dsh_agent_model.py container/dsh_deepagents_sdk.py /opt/dsh/deepagents/lib/python3.14/site-packages/
COPY container/deepagents-managed.py /usr/local/bin/deepagents
COPY container/dsh-cli-managed.py /usr/local/bin/dsh-cli
COPY container/deepagents-managed.toml /etc/dcode/managed_config.toml
COPY config/managed-agents.json /opt/dsh/config/managed-agents.json
COPY scripts/managed_agent_policy.mjs scripts/render_managed_agent_profile.mjs scripts/enforce_single_model_profiles.mjs scripts/install_single_model_startup.py /opt/dsh/scripts/
RUN node /opt/dsh/scripts/render_managed_agent_profile.mjs && node /opt/dsh/scripts/enforce_single_model_profiles.mjs /opt/dsh/seed/dsh-home && chown -R 10001:10001 /opt/dsh/seed/dsh-home && python3 /opt/dsh/scripts/install_single_model_startup.py && chmod 0755 /usr/local/bin/deepagents /usr/local/bin/dsh-cli && ln -s /usr/local/bin/dsh-cli /usr/local/bin/dsh-run && ln -s /usr/local/bin/dsh-cli /usr/local/bin/dsh-sdk && ln -s /usr/local/bin/deepagents /usr/local/bin/dcode && chown -R root:root /etc/dcode /opt/dsh/deepagents /opt/dsh/config/managed-agents.json && chmod -R a-w,a+rX /etc/dcode /opt/dsh/deepagents && chmod 0644 /opt/dsh/config/managed-agents.json
RUN /opt/dsh/deepagents/bin/python -I -c 'from deepagents import create_deep_agent; from dsh_agent_model import DSHManagedChat; from dsh_deepagents_sdk import create_dsh_agent'
# The DSH runtime base keeps its default user (root); workspace pods run as 10001:10001 (pod securityContext),
# and start-dsh plus the build checks below rely on the base default. So this candidate does not change USER.
