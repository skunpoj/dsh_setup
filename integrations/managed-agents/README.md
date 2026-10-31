# Managed coding-agent integration candidate

Status: opt-in source candidate. No image build, installation, deployment or native Deep Agents session is claimed by this directory.

The existing DSH runtime supports DSH, Claude Code, Kilo and TrueForge. This candidate adds Deep Agents Code (dcode) and friendly aliases for the existing DSH CLI. It does not turn the DSH chat UI into a universal frontend for other CLI agents.

## Interfaces and isolation

- Web Terminal runs actual installed CLI programs; behavior depends on their versions, settings, terminal capabilities and working directory.
- DSH web chat uses DSH's own harness. A prompt is not automatically forwarded to another CLI.
- DSH's CLI has interactive and headless modes. The inspected SDK uses JSON-RPC over stdio; complete SDK sessions still require qualification.
- CLI agents in the same workspace container can share files, tools and resources. Their conversations, context, approvals and resumable sessions remain separate.
- OpenShell can complement the terminal as a controlled execution backend. Neither inherently requires the other. This candidate does not install or qualify OpenShell.

## Build and install

This directory is an independent Docker build context. Keep the root product image and its pinned DSH package unchanged while reviewing it.

Deep Agents Code 0.2.2 requires Python 3.14. The overlay copies a separate Python 3.14 interpreter and virtual environment; existing system Python and Jupyter remain in place. Use reviewed immutable Bookworm-compatible images:

~~~sh
docker build integrations/managed-agents \
  --build-arg DSH_BASE_IMAGE="$DSH_BASE_IMAGE" \
  --build-arg PYTHON314_IMAGE="$PYTHON314_IMAGE" \
  --build-arg DSH_LITELLM_NAMESPACE=dsh \
  -t dsh-managed-agents:candidate
~~~

Both image arguments must contain an immutable sha256 digest; no deployment-specific image is committed here. Resolve and review the transitive wheel dependencies, licences and native ABI before promotion. Top-level package versions are pinned; this is not a complete dependency lock.

The build expects the existing seed-profile path, managed transport and exactly one workspace-policy startup anchor. It refuses incompatible startup layouts. The package import check in the Dockerfile has not yet been run in a built image.

After a qualified image build, intended commands are:

~~~sh
deepagents
# dcode is the same managed launcher
dsh-cli
dsh-run "Read README and explain the project"
dsh-sdk
~~~

Launch from a private project below /workspace. The SDK alias selects the installed DSH SDK mode; a tested external client workflow is still required. The optional Python helper requires an explicitly supplied private checkpointer. Filesystem virtual mode is not a process sandbox.

## Model and credential policy

The example policy permits only the gateway model ID deepseek-v4.1-flash. Operators must independently map that route to the intended immutable backend/checkpoint. A route name does not prove model provenance.

Root-owned managed configuration fixes the endpoint and launcher options. The assigned runtime credential is read only inside the runtime process; it is never committed. Client environment/provider overrides are rejected or cleared. Stored profiles are narrowed with original-byte backups and unrelated plugin/capability metadata preserved.

The request-policy module is a tested helper, not an installed authenticated gateway. Model-scoped credentials and authenticated gateway enforcement are mandatory. General Internet egress can bypass managed clients: deploy a fail-closed controlled outbound proxy/allowlist before claiming every shell user is restricted to one provider. Kubernetes egress policies are additive; an existing broad allow must be reconciled, not overlaid with another allowlist.

Application admins should receive the same restricted model credentials as other users. Infrastructure owners who can change the policy cannot be made unable to change it by that same policy.

## Validation and rollout

~~~sh
node --input-type=module -e "const t = await import('./integrations/managed-agents/tests/test_managed_agent_policy.mjs'); console.log(t.default)"
python3 -m unittest discover -s integrations/managed-agents/tests -p 'test_managed_deepagents.py' -v
~~~

Source validation: 29 JavaScript checks and 17 Linux Python test groups passed. Python tests use synthetic model/client classes; they do not qualify real package APIs, TUI configuration, model behavior or performance.

Before deployment: build and inspect the actual image; verify real package/config loading; test profile migration/idempotence in disposable fixtures; bind an authenticated single-model gateway; qualify outbound restrictions; then test one isolated user, CLI/SDK sessions, tool approvals and recovery. Match the running digest and affected behavior before promotion. Preserve user history, volumes, credentials and active-session recovery.

## References

- [Deep Agents SDK](https://docs.langchain.com/oss/python/deepagents/overview)
- [Deep Agents Code](https://docs.langchain.com/oss/deepagents/code/overview)
- [Managed configuration](https://docs.langchain.com/oss/deepagents/code/configuration)
- [Custom provider configuration](https://docs.langchain.com/oss/deepagents/code/config-file)
- [Claude Code gateways](https://code.claude.com/docs/en/llm-gateway): non-Claude models require independent compatibility qualification.
- [LiteLLM scoped virtual keys](https://docs.litellm.ai/docs/proxy/virtual_keys)
