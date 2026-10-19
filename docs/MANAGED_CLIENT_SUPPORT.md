# Managed coding clients inside DSH

## JupyterLab notebooks

Run `jupyter lab` in the selected environment's terminal, then open `/proxy/8888/lab` on the same DSH site. Python notebooks use that user's workspace and existing network/permission boundary. No Internet notebooks retain central CIFS storage; Internet notebooks stay separate. See [JupyterLab usage, security and setup](JUPYTERLAB.md).

DSH remains the main web interface. Claude Code, TrueForge and Kilo CLI run as optional clients inside the selected private DSH execution environment. They share the internal LiteLLM/model service, not another user's project files, credentials or client histories.

## Compatibility and acceptance

| Client | Pinned version | Recorded acceptance |
|---|---|---|
| Claude Code | 2.1.301 | Ordinary exact reply in 1.17 seconds in the 1017 checks |
| TrueForge | 0.179.2 | Ordinary exact reply in 0.73 seconds; saved assistant content verified |
| Kilo Code CLI | 7.8.12 | Exact ordinary reply in 9.05 seconds in a No Internet canary; saved output, actual read tool and session persistence across pod replacement verified |

The Kilo image is deployed to **all 20 main DSH runtimes**. The rollout preserved **167 existing history IDs and 189 session files byte-for-byte**, with mounts unchanged and no GPU model restart. Native DSH also passed three exact persisted ordinary replies at one and two concurrent clients on the new image. Existing additional owner instances were not changed by this rollout. The Kilo timing includes client startup and is a single compatibility sample, not a controlled speed comparison with the other clients.

The actual non-root canary rejected model/sharing overrides, denied writes to the operator policy, ignored hostile project/environment overrides, and failed both public-domain and direct-IP HTTPS probes while internal inference worked. [Sanitized acceptance summary](context-evidence/KILO_SUPPORT_20261019.json).

These ordinary checks do not substitute for a client-specific near-1M trial. The native DSH million-token, substantial-output, tool and concurrency results remain in the [checkpoint report](MODEL_UPDATE_1017.html). Configuring a 1M client budget is not itself proof of a successful 1M turn in that client. The centralized DSH usage counters do not currently include independent CLI session accounting.

## Use Kilo from the web terminal

Sign in, choose the appropriate environment, and open the authenticated DSH terminal. Work within the selected private `/workspace`:

```sh
kilo --version
kilo
# Or submit an ordinary non-interactive request:
kilo run --format json "Reply exactly KILO_READY"
```

The managed launcher selects `dsh-internal/deepseek-v4.1-flash`, pointing to the internal LiteLLM route and the installed DeepSeek-V4.1-Flash-1017 checkpoint. No Kilo cloud account is required for this provider. Kilo is used as a terminal client; this integration does not add a browser IDE extension or expose a new unauthenticated server.

Kilo stores data, local state and cache beneath `/state/kilo`, independently of Claude, TrueForge and native DSH histories. Its durability follows that runtime's `/state` mount. The Internet and No Internet environments retain separate state and workspace mounts; signing into another environment does not copy client histories. The new client does not migrate, clone or delete existing histories.

## How the three controls apply

**Prevent external leakage.** The launcher uses an operator-owned provider policy, enables only the internal provider, disables project-level provider configuration and removes inherited configuration/proxy overrides. Automatic sharing, OpenTelemetry, automatic updates, public model-catalog refresh, default plugins and LSP downloads are disabled. The No Internet runtime's infrastructure policy remains the enforcing public-network boundary; the Internet environment remains Internet-capable by design. No new public-destination allowance is introduced to install or run Kilo.

**Prevent damage or excessive access.** Kilo runs as the same non-root identity as its private execution workload, with the same scoped mounts, dropped capabilities and resource limits. Workspace read/search tools are permitted; other tool actions request approval. External-directory access is denied in the supplied client policy, and no host socket or elevated sandbox permission is added. Client permission prompts complement operating-system/storage permissions; they are not a replacement for those boundaries.

**Keep results contained.** Sharing and cloud/remote commands are disabled in the supported launcher. Sessions remain in private runtime state. The existing authenticated terminal gateway controls browser access; installing Kilo does not add a public publication route or give administrators ownership of another user's files. Authorized users can still copy content, and ordinary shell access can invoke programs independently of the launcher. The operator policy is not represented as an unbypassable sandbox for arbitrary code; the container/network/storage boundaries remain authoritative.

## Setup and maintenance

The Dockerfile installs `@kilocode/cli@7.8.12` during the approved image build. No Internet runtime startup performs no package download. The build places root-owned policy in `/etc/kilo/kilo.json` and installs the `kilo`/`kilocode` managed launchers. Credentials are read at runtime from the existing model-scoped `/harness-credentials/api-key` Secret mount, rather than included in the image or report. Generic deployments must adapt the operator-owned LiteLLM URL to their approved internal service.

Retain one-hour provider and stream deadlines to accommodate cold preparation. Context/output budgets are 1,048,576/8,192 tokens; exact final-envelope counting, output reserve and bounded long admission remain enforced by the shared gateway. A long-running client must not bypass those controls by selecting a direct model endpoint.

Before promotion, test the actual built binary as non-root: version, resolved internal provider, refusal of unauthorized provider/sharing options, correct ordinary output, private saved session, a bounded file tool operation, persistence and public-network denial in No Internet. Preserve image digest, private runtime specs and history fingerprints before replacing runtimes. Do not restart the GPU model merely to install a client.

The integration follows Kilo's official [CLI installation and configuration](https://kilo.ai/docs/code-with-ai/platforms/cli) and [custom-model configuration](https://kilo.ai/docs/code-with-ai/agents/custom-models). Package upgrades require review and repeated managed-policy/runtime checks; no automatic production upgrade is enabled.
