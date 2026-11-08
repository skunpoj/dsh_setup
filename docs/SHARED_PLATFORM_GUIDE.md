# Shared platform guide for coding clients

Successful signup enables your private **No Internet / Internal** workspace immediately, without individual administrator approval. **Only Internet access requires a separate administrator grant.** Account capacity controls are not an approval queue.

DSH, Claude Code, Kilo and TrueForge receive the same platform reference:
[`container/PLATFORM_GUIDE.md`](../container/PLATFORM_GUIDE.md). It explains private
environments, projects, persistent storage, approved dependencies, terminal and
Jupyter access, application names/ports/limits and managed inference. Client
conversations remain separate. This guide supplies context; infrastructure and
gateway authorization enforce access.

DSH, Web Terminal and JupyterLab share the **same `/workspace` mount within one
user and selected environment**, rather than synchronizing separate copies.
Files saved through one are available through the others. Select the same
project directory explicitly: terminal working directories and open notebook
folders do not automatically follow the active DSH project. Each client keeps
its own conversation state. No Internet and Internet workspaces remain separate.

Approved internal Git access does not require enabling public Internet. The
operator must configure the exact internal destination, DNS and trusted CA;
the user still authenticates to the repository with their authorized identity.
Keep TLS verification enabled and credentials out of repository URLs and logs.

| Client | Loading mechanism |
| --- | --- |
| DSH | A versioned managed block in private `/state/AGENTS.md` and `/workspace/AGENTS.md` |
| Claude Code | System-wide `/etc/claude-code/CLAUDE.md`, loaded by normal Claude Code sessions |
| Kilo | The readonly managed policy's `instructions` file list |
| TrueForge | A digest-gated adapter at the installed agent-definition instruction boundary, preserving the agent's existing instructions |

The guide does not discover or copy another client's history. Existing project
instructions outside its managed block remain unchanged. The first runtime
refresh retains the previous instruction file next to it for recovery. A changed
TrueForge package must be reviewed before applying the adapter; an unfamiliar
source digest refuses installation. Explicit client modes that disable instruction
discovery, such as Claude's `--bare`, are outside normal guide loading.

## Installation and updates

The runtime image installs the shared guide and client policy during its build:

```sh
python3 /opt/dsh/scripts/configure_platform_guide.py --image
```

Normal private-runtime startup refreshes DSH's managed block:

```sh
python3 /opt/dsh/scripts/configure_platform_guide.py --state /state --workspace /workspace
```

For an existing pinned image, an operator can use `scripts/platform_guide_overlay.py`
to generate an immutable readonly ConfigMap overlay. Preflight both installed
TrueForge resolver files, qualify the overlay on a disposable runtime, then
compose it with the existing deployment specification. Preserve images, private
volumes and other sidecars. Do not replace whole user instruction files.

For a fixed Internet-only, single-owner deployment, compose the operator profile
from `container/PLATFORM_GUIDE_INTERNET_ONLY_CONTEXT.md` using
`source_data(originals, deployment_context=context_text)`. The overlay gives
all four clients the same deployment-specific guide and retains its shared
version. Preserve that deployment's original startup/authentication and use its
actual DSH state directory when refreshing the managed instruction block.
Do not apply a main-platform startup wrapper to a different deployment layout.

## Client qualification

The 19 October disposable-runtime check used actual installed DSH, Claude Code,
Kilo and TrueForge with a random marker only in the loaded guide. The user prompt
did not contain that marker and prohibited file reads/tools. All four recovered
the marker, default allowance of eight application names and the fact that saving
a URL does not start the server. Recorded elapsed times were 2.094, 1.473, 9.179
and 0.672 seconds respectively. This establishes guide ingestion for those
normal client paths; it is not a throughput benchmark or a new 1M test.

Guide refresh and overlay tests also cover preserved project instructions,
idempotent updates, ambiguous-marker refusal, exclusive staging, unchanged data
mounts/images and retention of other sidecars. Production deployment and served
manual versions must be checked separately from this disposable qualification.

On 20 October, a read-only live audit of 34 main runtime environments found 34
distinct workspace mount scopes. DSH and Jupyter's supervisor in every runtime
read the same existing workspace instruction file with matching content, inode
and device. All 34 had the shared guide in DSH's instruction blocks, Claude's
system instruction file, Kilo's instruction list and both TrueForge resolver
adapters. Two sampled No Internet workers could reach their own application but
not the peer application. These checks do not constitute an exhaustive attack
test or a storage-server ACL audit. That audit preceded the guide refresh described below.


## Current rollout

Guide `2026-10-20.1` is deployed to all 34 main runtime environments and both
fixed Internet-only owner instances. Their existing histories, project files,
Jupyter settings, private instructions, images and storage mounts passed the
per-worker preservation checks. Replacements waited for idle workers.

All four installed clients recovered the guide through their normal instruction
loading in disposable main and fixed Internet-only profiles. The prompt did not
supply the expected guide facts, and file-reading tools were disabled for those
checks. Fixed instances correctly describe their Internet-only access and do not
advertise the main service's self-registration or No Internet choice.

Held native login sessions survived replacement in 33 main cases; the first
empty worker had no preceding session to preserve. Both fixed-instance owner
logins survived replacement, and replay of their logged-out cookies was denied.
The main internal-Git startup hook and future provisioning templates were also
updated after separate startup and persistence qualification. Credentials and
repository permissions remain separate from TLS trust configuration.

Rollout summary. This is
guide and startup qualification, not a new model-throughput or 1M benchmark.

## Fresh signup acceptance

A newly registered main-platform account also passed actual guide ingestion in
all four installed clients, cross-tool file reads/writes through DSH, terminal
WebSocket and a Jupyter kernel, and authenticated internal Git cloning while
public Internet remained blocked. Its saved notebook, theme, guide/Git settings
and two DSH conversations survived an actual pod replacement. The disposable
account was then disabled with its data retained. Follow the
workflow and acceptance scope.
