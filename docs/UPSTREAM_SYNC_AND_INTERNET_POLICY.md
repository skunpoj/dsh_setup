# DSH upstream synchronization and internet policy

## Verified production context boundary

The initial static-0.92 deployment failed a real approximately 262K-token request with a CUDA OOM. Subsequent controlled tests on the same four-H100 node progressed through 256K and 512K, including failed configurations and rollback, to a successful 1,000,015-input-token request with static 0.90, prefill chunk 1,024 and max prefill tokens 2,048. The model ceiling is 1,048,576 total tokens. This does not establish unrestricted 1M concurrency or full-window output quality.

DSH and LiteLLM still enforce 131,072 total tokens, an 8,192 output ceiling, a 256-token LiteLLM safety buffer and compaction around 98,304 tokens. Product-level admission, long-session compaction and end-to-end gates remain before exposing a larger budget. The complete trial matrix, failures, evidence limits and rollback are in [CONTEXT_OPTIMIZATION_20261015.md](CONTEXT_OPTIMIZATION_20261015.md).

## Deployed source layers

The deployment installs a published `@deepseek-ai/dsh` package and then applies repository-owned configuration and compatibility patches from `scripts/configure_models.js`. The enterprise authentication gateway in `scripts/auth_proxy.js` is also repository-owned. These files are overlays; they are not part of the official DeepSeek Harness repository.

The current upstream comparison is:

| Item | Revision inspected |
| --- | --- |
| Deployed package baseline | `dsh-v0.2.0-rc.2` |
| Official upstream | `deepseek-ai/deepseek-harness` `master` at `571902028a75c64c1d767f4ae5fd099485f0ddf0` |
| Latest upstream tag inspected | `dsh-v0.2.1-alpha.3` (`2fbf4359b8`) |

These references were fetched again on 15 October 2026. Official `master` and the
latest inspected tag were unchanged, so no upstream source was incorporated into
the enterprise overlay in this update.

The upstream interval changes thousands of files and includes Session v4 persistence, remote-access principals, permission policy, web tools, sandbox behavior, compaction, attachment handling, plugin composition, and the Web client. Treating it as a drop-in package update would put stored sessions and runtime byte patches at risk.

## Synchronization procedure

1. Record the deployed package version, running image digest, ConfigMap hash, and coherent backups of the current `/state` and `/workspace` volumes (legacy `/workspace/dsh_storage` separately).
2. Fetch official upstream tags into a separate checkout. Never merge upstream source into this deployment repository.
3. Compare the next published tag with the pinned baseline. Review Session format and upgrade guides first, followed by every package file currently modified by `configure_models.js`.
4. Build a candidate image that already contains the selected DSH package and operating-system dependencies. Do not depend on network package installation during pod startup.
5. Reapply each enterprise requirement through documented configuration or a Cordis plugin when upstream exposes an extension point. Retain byte patching only when no supported extension exists, and make every patch fail loudly when its expected source text changes.
6. Restore a copy of Production data into an isolated candidate environment. Verify login, existing Session reads, new prompts, compaction, attachments, model calls, tools, terminal, dynamic application proxy, and orderly restart persistence.
7. Deploy with a rollback image and the preserved ConfigMap. Read back the running image digest and mounted scripts, then repeat the affected behavior tests.

## Working-environment selection on the login page

The enterprise login page provides `No Internet / Internal` and `Internet`, with `No Internet / Internal` selected initially. The wire values remain `off` and `on` for compatibility. On successful login the gateway:

- validates the credential before accepting the selection;
- stores the user's most recent selection in `/auth/.user_settings.json` in the environment gateway with mode `0600`;
- binds the selection to the new in-memory authenticated session;
- exposes the authenticated result at `GET /api/auth/session`; and
- forwards `X-DSH-Internet-Access: off|on` and `X-DSH-User` to the DSH Web service.

`scripts/auth_proxy.js` now supports session-sticky routing to two backend targets. The selected environment is fixed in the authenticated session and is used for HTTP, WebSocket and application-proxy traffic. The compatibility response field `internet` is retained and `GET /api/auth/session` also reports `environment: secure|internet`.

## Implemented deployment architecture

The repository includes a prebuilt runtime image and two execution pools behind a standalone authenticated gateway:

- an offline pool with default-deny egress and explicit DNS plus in-cluster LiteLLM access;
- an online pool with the approved outbound policy; and
- routing that binds each authenticated Session to exactly one pool for its lifetime;
- separate RWO state volumes, so live DSH session files are never written concurrently by both pools;
- a separate protected local workspace mounted only by the Secure pool; central DA_WORKSPACE persistence remains to be restored; and
- a separate staging PVC mounted by the Internet pool.

`Dockerfile` bakes the DSH package, Node, Python, terminal and operating-system dependencies into the image. `container/start-dsh.sh` starts without package installation, keeps each pool's state on its own PVC and publishes its process token to the gateway through the restricted routing-token directory. `k8s/dsh-environment-pools.yaml` and `k8s/dsh-environment-gateway.yaml` define the runtime.

The two pools deliberately do not multi-write the same session directory. Identity and login settings are central at the gateway, but active session state belongs to the chosen environment. Authentication, the Secure workspace, incoming packages, approved packages, each environment's runtime state, Internet staging and each launch token use separate local RWO volumes. This avoids the root-only ownership behavior verified on the legacy CIFS share and prevents one environment from mounting another environment's workspace, token or package area. During controlled cutover, the suspended `dsh-migrate-secure-state` Job performs three distinct migrations: gateway identity files into `dsh-auth-state`, project files into `dsh-secure-workspace` while excluding `users` and `dsh_storage`, and the complete legacy `dsh_storage` tree into `dsh-secure-state`. The separation is intentional: runtime history, sessions, attachments, settings, and credentials belong under `/state`, not in the project workspace. The Job then assigns UID/GID `10001`, protects `.credentials.yaml` with mode `0600`, and fails unless the authentication store is non-empty and `/state/sessions` exists. Moving project data to the Internet environment requires an approved copy into its staging PVC. This prevents an Internet-capable process from reading the protected workspace and avoids file-lock and history corruption from concurrent writers.

## Offline dependency acquisition

The Internet environment supplies dependencies to Secure without receiving the protected workspace:

1. In Internet, `prepare-offline-deps python requirements.txt` downloads Python wheels and source distributions to `/packages/incoming/python`. `prepare-offline-deps npm <project-directory>` populates `/packages/incoming/npm-cache` from a locked Node project without running package lifecycle scripts.
2. An operator reviews the package names, source and security results and writes exact SHA-256 plus relative-path rows to the `dsh-package-approval` ConfigMap.
3. The suspended `dsh-promote-approved-packages` Job is resumed for that approval. It rejects empty manifests, absolute or parent paths, missing artifacts and hash mismatches, then copies verified files read-only into `/packages/approved`.
4. Secure mounts only `/packages/approved` read-only. Python has `PIP_NO_INDEX=1` and resolves through `/packages/approved/python`; npm has offline mode enabled and resolves through `/packages/approved/npm-cache`.

Internet never mounts the approved directory or protected workspace. Secure never mounts incoming and cannot reach public package repositories. This allows Internet-assisted installation while keeping the security boundary and preventing uncontrolled multi-writer access.

The package-transfer volumes were verified on the live one-node cluster with UID/GID `10001`: Internet's incoming volume accepted a write, Secure's read-only approved mount rejected a write, and the promotion script copied a test artifact only after its SHA-256 matched, setting the promoted file mode to `0444`.

Deployment remains gated on building and pushing the referenced image, creating `dsh-runtime-secrets`, backing up the current workspace, and exercising the isolated manifests with restored test data. Existing Production workloads remain the rollback route until the new gateway passes login, history, prompt, tool, terminal, restart and egress tests.

`k8s/dsh-egress-policies.yaml` defines the enforcement boundary. Pods labelled `dsh.bot.or.th/egress-mode=offline` may resolve cluster DNS and call LiteLLM on TCP 4000, while public egress is denied. Pods labelled `dsh.bot.or.th/egress-mode=online` retain egress. The policies do not select unlabeled Production pods.

On 15 October 2026, `tests/test_egress_policies.ps1` was exercised against the live Calico cluster. The offline canary timed out when connecting to GitHub, returned HTTP 200 from LiteLLM liveliness, and the online canary returned HTTP 200 from GitHub. This proves policy enforcement; it does not prove that the login toggle routes a user to a pool.

## Shared-model scheduling validation

The model's `interactive-v2` overlay is maintained in GPU_server, not in the DSH package overlay. It matches queued cache prefixes before reserving up to 512 prefill tokens, retains long-request progress, and uses mixed chunking plus a decode interval of four. The first revision passed tiny prompts but failed cached 24K sessions; V2 passed both. See [the full scheduling record](SCHEDULING_FAIRNESS_20261015.md).

Before changing either the model image or client prompt construction, repeat the fresh-input and continuing-session interference gates. Preserve the original scheduler source-hash check and review it against the next image; do not blindly rebase or accept a new hash. The present 128K client guardrail remains in force. Large uncached history can still queue, and near-1M mixed-load behavior has not been revalidated.


## Runtime rollout verified — 15 October 2026, 20:39 ICT

Build 62702 is deployed in gateway, Secure and Internet. Read the [actual rollout procedure, restart/persistence results and rollback limitations](DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.md) and [live evidence](context-evidence/runtime-rollout-live-20261015.json). Secure retained 80 listed histories and 2,732 checked files; Internet retained controlled markers. Coherent local snapshot PVCs were retained; no central DA_WORKSPACE synchronization or full restore was established. Use Recreate and actual application health probes; do not run two state writers or co-mount live state in a verifier pod. The GPU configuration was not changed by this rollout.


## Central workspace corrected — 15 October 2026, 21:32 ICT

Secure `/workspace` now directly mounts DA_WORKSPACE through `dsh-da-workspace-secure`, subpath `dsh`, as non-root UID 10001. Conflict-preserving reconciliation, independent peer readback, another runtime restart and held/fresh login checks passed; Secure still lists 80 histories. A first validator compatibility error triggered an actual mount rollback; the portable validator and retry passed. Active `/state` remains local, with a verified central coherent baseline but no continuous synchronization. See the [current storage guide](MULTI_TENANT_STORAGE_AND_PERSISTENCE.md) and [live correction record](context-evidence/central-workspace-live-20261015.json). Do not apply historical local-workspace manifests or rerun the old migration job as if they were the current storage design.
