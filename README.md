# Private AI Workspaces - Kubernetes and 1M Context

## Managed provider login

Keep the team gateway login and native DSH authentication. Managed LiteLLM profiles hide the separate official DeepSeek account sign-in. See [the login guide](docs/MANAGED_PROVIDER_LOGIN.html) for user steps, configuration and hot reload.

## Three risk controls

Start with [the design and operating principles](docs/THREE_RISK_CONTROLS.md) or its [HTML guide](docs/THREE_RISK_CONTROLS.html): prevent external leakage, prevent damage or excessive access, and keep results within authorized users. GPU configuration and measurements belong in the technical references after the controls. [Risk-first course delivery](docs/COURSE_DELIVERY.md) explains authenticated video, captions, source snapshots and safe updates.

## AD / LDAP authentication

Start with the [user manual](docs/DSH_USER_MANUAL.md) or its [standalone HTML version](docs/DSH_USER_MANUAL.html) for sign-in, private environments, tools, application URLs and administrator controls. The [current-guide policy](docs/CURRENT_GUIDE.md) describes the single deployment guide and preserved archives.

Optional verified LDAPS sign-in supports private No Internet accounts with Internet access approved separately by an administrator. An AD username that conflicts with an existing local account is rejected with a clear instruction to contact an administrator to delete that local account; no account or history is automatically merged or deleted. Existing local recovery sign-in remains available. The 23 October main-gateway rollout verified AD/UPN application sign-in, conflict refusal and history preservation; see the [acceptance record](docs/LDAP_APP_LOGIN_ACCEPTANCE_20261023.md). See [configuration, collision handling and tests](docs/LDAP_AUTHENTICATION.md).

## Authenticated application sharing

Owners can explicitly share an ordinary local web app with enabled DSH users while keeping JupyterLab, terminals, workspaces and histories private. Existing mappings remain owner-only. See the [sharing guide](docs/AUTHENTICATED_APP_SHARING.md) or its [HTML version](docs/AUTHENTICATED_APP_SHARING.html) for setup, isolation boundaries and application responsibilities.

## Public presentation and speaker guide

[Editable PowerPoint](docs/presentations/guarding-the-value-stream/Guarding_the_Value_Stream.pptx) ยท [Slide PDF](docs/presentations/guarding-the-value-stream/Guarding_the_Value_Stream.pdf) ยท [Detailed storytelling PDF](docs/presentations/guarding-the-value-stream/Guarding_the_Value_Stream_Story.pdf)

The 23-slide talk covers agent incidents, controls, governance, illustrative banking and insurance workflows, and DSH. Its final QR links to this repository. Research infographics are credited to **Thanatchon Chongmankhong** ([HarnessWatch](https://thanatchon36.github.io/harnesswatch/paper/) and [airmkit](https://thanatchon36.github.io/airmkit/paper/)). The examples are hypothetical and are not a claim of live business automation or certified compliance.

This public tree is a **portable fresh-install reference**, not the latest deployment source or operational history of an institution. Private implementation and evidence must remain in an access-controlled repository. See [publication boundaries](docs/PUBLICATION.md).

A configurable deployment of DeepSeek Harness, internal LiteLLM and a four-GPU
SGLang backend. The repository includes the GPU manifests, model-download job,
storage, context guard, scheduler overlays, private user environments and setup
instructions. No separate infrastructure repository is required.

This is a **fresh-install reference**, not an export of an existing organization
or a promise that any four-GPU machine will sustain 1M context. Model weights,
hardware, storage drivers, domain names, certificates and credentials are supplied
by the operator. The public examples contain no real deployment addresses,
personal accounts, operational transcripts or credential values.

## What it provides

- One private non-root runtime, workspace and history volume per user/environment.
- No Internet as the main login default; separate Internet dependency preparation.
- Protected local password records, owner-bound routing and an admin access log.
- Managed Claude Code and TrueForge configuration using model-only client keys.
- SGLang tensor parallelism across four GPUs, 1,048,576 total-token capacity,
  chunked prefill and fail-closed scheduler compatibility checks.
- LiteLLM authentication, PostgreSQL-backed virtual keys and a loopback final-wire
  context guard. Text above 32K counted input plus reserved output uses bounded
  managed admission; shorter requests can remain concurrent. Input includes the
  complete conversation and tool context, not only the latest prompt. That is not two simultaneous full-1M requests or an SLA.
- Persistent storage and read-only approved packages. Persistence is not backup.

## Start here

1. Read [prerequisites and complete installation](docs/INSTALL.md).
2. Copy `config.example.yaml` to ignored `config.local.yaml`; supply your storage,
   domain and built runtime-image digest. Never put credentials in that file.
3. Render `generated/` with `python scripts/render_k8s.py --config config.local.yaml --output generated`.
4. Follow the ordered namespace/storage, Secret, model-download, platform and
   client-key steps in the guide. Do not apply everything before downloading weights.
5. Perform [acceptance tests](docs/ACCEPTANCE.md) before allowing real workloads.

The renderer refuses unresolved placeholders. It never reads a live cluster or
renders Secret values. Helpers create fresh Secrets through stdin, do not print
their values and refuse to overwrite existing credentials.

## Architecture

```mermaid
flowchart TB
  U[Authenticated user] --> G[Gateway and protected account store]
  G --> N[Private No Internet runtime]
  G --> I[Private Internet runtime]
  N --> P[Own workspace and history]
  I --> Q[Separate workspace and history]
  N --> L[Authenticated LiteLLM]
  I --> L
  L --> F[Loopback final-wire context guard]
  F --> M[SGLang on four GPUs]
  L --> DB[Private PostgreSQL]
  I --> C[Private incoming packages]
  C --> O[Operator review and hash promotion]
  O --> A[Approved cache mounted read-only]
  A --> N
```

The browser does not select a backend host. The server binds each login to an
operator-provisioned user/environment mapping. Runtime pods have no account-store
mount or Kubernetes API token. No corporate identity provider or datalake is
implicitly configured. [Security boundaries](docs/SECURITY.md).

## Context and performance

The corrected-route qualification reserved **1,002,081 input / 8,192 output tokens**, but failed its memory-warning gate before a substantial near-1M answer. **53 ordinary replies** passed with median **4.66 s** and maximum **11.78 s**, without retries. Compaction was not started and no new 100+ tokens/sec result is claimed. The compatible unfused profile was restored with the 1M ceiling retained; a fresh canonical native DSH recovery reply passed in **3.825 s**, zero retries. Earlier trials remain separate records. [Qualification results and recovery scope](docs/GPU_PREPARATION_REVIEW_20261022.html).

The reference profile reserves up to 8,192 output tokens and 256 proxy tokens.
With that full output reservation, maximum counted input is 1,040,128 tokens.
DSH automatic compaction is configured near 917,504 estimated tokens, with exact
wire budgeting enforced separately. Long prefill can take minutes and reduce
short-request throughput. Use [the tuning guide](docs/CONTEXT_1M.md); qualify your
own memory margin, cancellation, tools and mixed load before increasing limits.

## Verification and maintenance

```sh
python -m pip install -r requirements-dev.txt
python scripts/scan_public.py .
python -m unittest discover -s tests -p 'test_public_manifests.py'
node tests/test_password_store.js
node tests/test_workspace_policy.js
```

Pinned package/image compatibility checks fail closed on upstream changes. A
source or schema test is not proof of successful GPU inference. Keep local
configuration, generated manifests, keys, tickets, backups and results out of Git.
See [release validation](docs/VALIDATION.md) and [third-party notices](docs/THIRD_PARTY.md).

For custom automatic provisioning, see [signup capacity, pressure gating and automatic recovery](docs/SIGNUP_CAPACITY.md). The portable evaluator is supplied for integration; it does not install a collector or enable registration.

## Application access and proxy setup

Private local applications and explicitly approved HTTPS destinations can use owner-bound app URLs, with DSH sign-in required by default. See the [application proxy setup and regression checks](docs/APP_PROXY.md) for origin policies, DNS/TLS, optional Gradio compatibility and destination-authentication boundaries.

For existing installations that cannot restart immediately, the optional [managed-client compatibility layer](docs/LIVE_CLIENT_COMPATIBILITY.md) applies only to new launches. It preserves existing processes and history; permanent image adoption remains separate.

## DeepInfer candidate

The [DeepInfer integration guide](docs/DEEPINFER_INTEGRATION.md) includes a pinned,
read-only hardware/source gate and the H100 porting requirements. The reviewed
official candidate requires SM100 kernels; the existing four H100/SM90 GPUs fail
that gate. DeepInfer is not installed or benchmarked; SGLang remains the serving
engine. This gate does not change DSH accounts, files, histories or model routing.

## DeepInfer on four H100 GPUs

The 23 October read-only review found that official DeepInfer revision `9bd9cf2`
still requires SM100 attention/MoE paths; the installed four H100s are SM90.
DeepInfer was not installed or benchmarked, and SGLang remains in use. There is
no matched DeepInfer-versus-SGLang 1M compaction or throughput result.
See the [compatibility and comparison status](docs/DEEPINFER_INTEGRATION.html)
or [Markdown guide](docs/DEEPINFER_INTEGRATION.md) for the source checks,
recorded SGLang results and same-node qualification gates.


## GPU status — 23 October 2026

The 23 October GPU candidate was rejected at the allocator-warning gate after passing 128K/384K stages. Four short DSH conversations overlapped at 117.75 combined output tokens/sec (30.07–33.77 per conversation including whole-turn time); this does not establish 100+ per conversation or two simultaneous 1M requests. The saved baseline retains the 1M ceiling. See the dated results for definitions and recovery checks. [Detailed results](docs/GPU_TRIAL_STATUS_20261023.html).


### Jupyter Start

Start safely reuses an already-enabled Jupyter service across Main DSH, DSH2 and DSH3.
[Administrator controls](docs/JUPYTER_START_CONTROLS.html) and the
[captioned walkthrough](docs/JUPYTER_DSH2_DSH3_WALKTHROUGH.html) explain Start, Stop and Restart.


## Current guide and lifecycle verification

See [document alignment](docs/DOCUMENT_ALIGNMENT_20261023.md) for current controls, tests and historical-media limits.

## Jupyter automatic startup

Private workspaces seed managed Jupyter in both environments. Internet startup still requires admin-approved Internet access. Autostart recovers the saved desired state after replacement; Admin Stop stays disabled. Existing on-demand servers are left running until natural handover, preserving active notebooks. Saved files and settings remain in their private storage. See the [lifecycle guide](docs/JUPYTER_APP_LIFECYCLE.html) and [operator backfill procedure](docs/JUPYTER_AUTOSTART_BACKFILL.html).
