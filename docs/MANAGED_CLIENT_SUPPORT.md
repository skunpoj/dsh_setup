# Managed coding clients inside DSH

DSH and its clients can use shared inference on another machine through the approved gateway. Current policies use the stable internal LiteLLM alias; moving that service outside the cluster needs an operator-managed relay or coordinated endpoint policy changes. OpenAI clients use `/v1`, while Claude's base origin omits that suffix. Jupyter runs locally in the private runtime and calls inference only when notebook code explicitly requests it. See [flexible deployment and client address configuration](FLEXIBLE_DEPLOYMENT.md).

## JupyterLab notebooks

Choose **JupyterLab** at sign-in or open `/proxy/8888/lab` on the same DSH site. Newly provisioned accounts have a managed No Internet notebook service; administrators can Stop or Start automatic recovery. Manual `jupyter lab` remains available in the owner terminal. Python notebooks use that user's workspace and existing network/permission boundary. No Internet notebooks retain central CIFS storage; Internet notebooks stay separate. See [JupyterLab usage, security and setup](JUPYTERLAB.md).

DSH remains the main web interface. Claude Code, TrueForge and Kilo CLI run as optional clients inside the selected private DSH execution environment. They share the internal LiteLLM/model service, not another user's project files, credentials or client histories.

## Compatibility and acceptance

| Client | Pinned version | Recorded acceptance |
|---|---|---|
| Claude Code | 2.1.301 | Ordinary exact reply in 1.17 seconds in the 1017 checks |
| TrueForge | 0.179.2 | Ordinary exact reply in 0.73 seconds; saved assistant content verified |
| Kilo Code CLI | 7.8.12 | Exact ordinary reply in 9.05 seconds in a No Internet canary; saved output, actual read tool and session persistence across pod replacement verified |

Kilo is included in the qualified prebuilt DSH runtime. The original 19 October installation rollout covered all 20 main runtimes present at that time. The rollout preserved **167 existing history IDs and 189 session files byte-for-byte**, with mounts unchanged and no GPU model restart. Native DSH also passed three exact persisted ordinary replies at one and two concurrent clients on the new image. Existing additional owner instances were not changed by this rollout. The Kilo timing includes client startup and is a single compatibility sample, not a controlled speed comparison with the other clients.

The actual non-root canary rejected model/sharing overrides, denied writes to the operator policy, ignored hostile project/environment overrides, and failed both public-domain and direct-IP HTTPS probes while internal inference worked. Follow the [managed-client validation procedure](https://github.com/skunpoj/dsh_setup/blob/main/docs/MANAGED_CLIENT_VALIDATION.md) when qualifying another deployment.

These ordinary checks do not substitute for a client-specific near-1M trial. The native DSH million-token, substantial-output, tool and concurrency results remain in the checkpoint report. Configuring a 1M client budget is not itself proof of a successful 1M turn in that client. The centralized DSH usage counters do not currently include independent CLI session accounting.

## Guide and file-tool verification

On 22 October, two disposable accounts were tested in both No Internet and Internet environments. DSH, Claude Code, Kilo Code and TrueForge each loaded the managed guide, read a hidden value from a workspace file and wrote the correct value to the next file. All **16 client turns passed**; observed elapsed times were **4.90–12.42 seconds**. The value and guide answers were not supplied in the prompt, and the resulting file contents were checked independently.

All four contexts could read their own completed DSH conversation. Eight cross-user and four cross-environment history requests were denied, including forged identity headers. Within one account and environment, clients share `/workspace` directly; terminal and notebook working directories are selected explicitly. Switching environments does not share that workspace or its histories.

The full image fixes are active in future-account templates and unassigned warm spares. Existing workspaces now also have the separate compatibility layer described below; that addition does not replace their image. These are ordinary client/tool checks, separate from near-1M qualification.

## Existing workspaces: launch the updated clients

The compatibility layer is installed in existing user/environment workspaces **without restarting them**. It enables the qualified Kilo editing policy and TrueForge workspace file tools for newly launched clients. Existing accounts, private storage, histories and running processes stay in place.

Open a **new interactive Bash terminal** before launching `kilo`, `kilocode` or `trueforge`. In an already-open Bash terminal, load the same launchers explicitly:

```sh
. /state/.dsh-managed-clients/current/activate.sh
```

This affects subsequent commands in that shell. Already-running clients retain their loaded code; finish those sessions before launching a replacement. Do not start a competing TrueForge server on an occupied port. Noninteractive commands, absolute executable paths and other shells do not automatically use Bash functions.

The qualified compatibility release and recovery copies persist in private `/state`. After a normal worker replacement, the persistent native DSH startup plugin restores Bash activation in Main workspaces; the two additional owner instances retain their complete HOME and activation. Open a new interactive Bash terminal to use the retained launchers. This restores client compatibility automatically; it does not launch agents or resume in-memory work. Already-running clients keep their loaded code. Provider permissions, network policy, private files and the underlying isolation boundary remain unchanged.

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

**Prevent damage or excessive access.** Kilo runs as the same non-root identity as its private execution workload, with the same scoped mounts, dropped capabilities and resource limits. Managed policies permit workspace read/search and, in the qualified editing launchers, bounded workspace edits. Approval behavior depends on the selected client and policy; the compatibility launcher does not require a prompt for every workspace write. External-directory access is denied by the supplied client policy, and no host socket or elevated sandbox permission is added. Client policy and approval prompts complement operating-system/storage permissions; they are not a replacement for those boundaries.

**Keep results contained.** Sharing and cloud/remote commands are disabled in the supported launcher. Sessions remain in private runtime state. The existing authenticated terminal gateway controls browser access; installing Kilo does not add a public publication route or give administrators ownership of another user's files. Authorized users can still copy content, and ordinary shell access can invoke programs independently of the launcher. The operator policy is not represented as an unbypassable sandbox for arbitrary code; the container/network/storage boundaries remain authoritative.

## Setup and maintenance

The Dockerfile installs `@kilocode/cli@7.8.12` during the approved image build. No Internet runtime startup performs no package download. The build places root-owned policy in `/etc/kilo/kilo.json` and installs the `kilo`/`kilocode` managed launchers. Credentials are read at runtime from the existing model-scoped `/harness-credentials/api-key` Secret mount, rather than included in the image or report. Generic deployments must adapt the operator-owned LiteLLM URL to their approved internal service.

Retain one-hour provider and stream deadlines to accommodate cold preparation. Context/output budgets are 1,048,576/8,192 tokens; exact final-envelope counting, output reserve and bounded long admission remain enforced by the shared gateway. A long-running client must not bypass those controls by selecting a direct model endpoint.

Before promotion, test the actual built binary as non-root: version, resolved internal provider, refusal of unauthorized provider/sharing options, correct ordinary output, private saved session, a bounded file tool operation, persistence and public-network denial in No Internet. Preserve image digest, private runtime specs and history fingerprints before replacing runtimes. Do not restart the GPU model merely to install a client.

The integration follows Kilo's official [CLI installation and configuration](https://kilo.ai/docs/code-with-ai/platforms/cli) and [custom-model configuration](https://kilo.ai/docs/code-with-ai/agents/custom-models). Package upgrades require review and repeated managed-policy/runtime checks; no automatic production upgrade is enabled.
