# Shared platform guide for coding clients

DSH, Claude Code, Kilo and TrueForge receive the same platform reference:
[`container/PLATFORM_GUIDE.md`](../container/PLATFORM_GUIDE.md). It explains private
environments, projects, persistent storage, approved dependencies, terminal and
Jupyter access, application names/ports/limits and managed inference. Client
conversations remain separate. This guide supplies context; infrastructure and
gateway authorization enforce access.

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
