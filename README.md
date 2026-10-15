# DSH — Enterprise Execution Environments and RDT Pilot

DSH combines a username-authenticated gateway, No Internet and Internet execution environments, internal LiteLLM and a shared four-H100 model. **The RDT pilot controls are partially implemented, not fully closed.**

Start with the [interactive security/architecture walkthrough](docs/DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.html) or its [Markdown source](docs/DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.md). The HTML is self-contained and includes SMP EDA-style diagrams with zoom, fullscreen, source copy and SVG/PNG export.

## Three pilot controls and how to close them

The walkthrough is structured around preventing external leakage, preventing source damage or excessive access, and containing reports/history within named-user permissions. Each control explains the threat, infrastructure/data/application enforcement, recorded behavior, remaining gaps and the evidence required before closure. It retains the original mounted-DA_WORKSPACE requirement and distinguishes it from read-only RDT access. This is a synthesis of dated evidence, not a new Production acceptance test.

## Features, design decisions and actual status

| Feature | Design reason | Status |
|---|---|---|
| No Internet / Internal default | Constrain generated code without relying on prompts | Live restricted-egress pool; not an air gap |
| Internet environment | Prepare dependencies without mounting protected data | Live separate staging/workspace/history |
| Authenticated session routing | Keep HTTP, WebSocket, terminal and applications in the chosen environment | Live environment routing; per-user routing only prepared |
| Safe runtime replacement | Keep state single-writer; detect backend-token rotation and actual application health | Build 62702 live in gateway and both pools; restart/login/content tests passed |
| Registration closed | Administrative account provisioning for a named pilot | Deployed and actual denial tested; approved pilot membership still pending |
| Approved package transfer | Supply offline libraries without sharing writable protected workspaces | Incoming, operator review, hash-checked promotion, read-only approved cache |
| Dedicated user runtime | Isolate execution, workspace, history and attachments | Generator and routing source tests pass; not deployed |
| Read-only RDT source | Prevent source modification and broad data access | Approved snapshot support prepared; dataset/account and negative tests pending |
| Central workspace | Preserve the original mounted-share design | Secure `/workspace` restored to CIFS; two-way peer and restart tests passed. Active `/state` remains local with a verified central baseline; continuous sync remains pending |
| Shared GPU service | Conserve the existing single-node four-GPU resources | Backend ceiling 1M; DSH/LiteLLM still 128K |
| Interactive scheduling | Keep short requests responsive during long prefill | Controlled 133K mixed-load tests passed; near-1M mixed load not revalidated |

## Architecture and security boundary

```mermaid
flowchart TB
 User[Authenticated user] --> Gateway[Environment gateway]
 Gateway --> Secure[No Internet - default]
 Gateway --> Internet[Internet staging]
 Secure --> Private[Secure workspace on CIFS]
 Internet --> Staging[Separate Internet workspace and state]
 Internet --> Incoming[Incoming packages]
 Incoming --> Review[Operator approval and hash validation]
 Review --> Approved[Approved cache - read-only in Secure]
 Approved --> Secure
 Secure --> LiteLLM[Internal LiteLLM]
 Internet --> LiteLLM
 LiteLLM --> GPU[Shared four-H100 model]
 Private --> DA[Mounted DA_WORKSPACE]
 Secure --> State[Local active state - verified central baseline]
```

The gateway authenticates and pins a login to an execution environment. Runtime NetworkPolicies enforce egress; choosing a radio button alone does not enforce it. Secure is allowed cluster DNS and internal LiteLLM. Internet has public access and does not mount protected source/workspace/history. DNS forwarding and indirect inference-service paths still require leakage acceptance checks.

Each current environment has its own writable PVCs, but users inside that environment share a process and volumes. Directory names are not a security boundary with shell/tool execution. The intended user-isolated design assigns a private pod, workspace PVC and state/history PVC to each approved identity/environment pair, sharing only inference and approved packages read-only. This is prepared, not live. See [per-user isolation](docs/PER_USER_ISOLATION.md).

Runtime containers run as UID/GID 10001, disable privilege escalation and drop capabilities. These controls limit privileges; they do not establish RDT authorization. Use a dedicated non-admin source identity and approved read-only snapshot/view. Write results separately. Verify actual source-write and out-of-scope-read denial before admitting protected RDT work.

No Internet is restricted egress, not a strict air gap. Browser/gateway, cluster DNS, storage and inference remain connected. An internal hostname alone does not prove a destination cannot relay externally.

## Storage — original mounted-share requirement

The [raw-transcript and Git audit](docs/DA_WORKSPACE_DESIGN_REVIEW_20261015.md) confirms that replacing DA_WORKSPACE with a node-local workspace was an assistant implementation deviation, not a user instruction. At 09:29 ICT the assistant chose the replacement; GitHub `9c3b571` recorded it at 10:21. The approved proposal still said “Store durable history centrally.” An isolated test now proves that UID/GID 10001 can write/read back on the same CIFS share when ownership is explicitly mapped. **Production was remounted successfully and verified at 21:32 ICT.** See the [live correction record](docs/context-evidence/central-workspace-live-20261015.json).

Restoring the existing DA_WORKSPACE mount is distinct from granting new RDT access or assigning shared histories to private users. A local workspace plus a central-backup proposal does not satisfy the original mounted-workspace requirement.

Secure `/workspace` now directly mounts DA_WORKSPACE through `dsh-da-workspace-secure`, subpath `dsh`. `/state` remains on the original local TopoLVM PVC. Internet retains separate local staging/state and does not mount the protected share. The old local workspace and legacy PV remain available for rollback. Workspace writes now land directly on CIFS; active-state writes do not automatically sync centrally.

Earlier claims about automatic CIFS shutdown flush, zero data loss and complete user isolation were not accurate for these new pools. The original documentation is preserved in [the legacy README](docs/archive/README_BEFORE_RECONCILIATION_20261015.md). The original CIFS workaround should not have silently changed central persistence policy.

Restore DA_WORKSPACE as the actual mounted workspace after reconciling newer local files with the share and preserving conflicts and rollback PVCs. Keep non-root execution using the tested CIFS ownership mapping; maintain environment/per-user subpath boundaries. Preserve central history while using suitable local runtime locking where necessary. Do not replace the mount requirement with backups or treat a copy of changing database files as a coherent backup. See [current storage guide](docs/MULTI_TENANT_STORAGE_AND_PERSISTENCE.md).

## Dependency workflow

1. Internet downloads candidate Python/Node artifacts to incoming storage.
2. An operator checks provenance, license/security results and exact SHA-256 values.
3. The controlled promotion job rejects unsafe paths, missing files and hash mismatches.
4. Secure reads approved artifacts through a read-only mount; Python no-index and npm offline settings avoid public repositories.

Hash matching proves integrity against the approved manifest, not package safety. Internet cannot directly install into Secure or write its workspace. Switching login environments does not copy project data or conversation history.

## Setup and controlled deployment

1. Build the pinned `@deepseek-ai/dsh@0.2.0-rc.2` runtime through the approved Azure pipeline; inspect packaged tests and pushed immutable digest. Startup must not install software from the Internet.
2. Provision reviewed Secrets, separate PVCs and the network policies in `k8s/dsh-egress-policies.yaml`. Do not put credentials in Git or reports.
3. For private runtimes, obtain approved identities and data scope, then run `scripts/generate_user_runtimes.py --users APPROVED_USERS --image REGISTRY/IMAGE@sha256:DIGEST --output candidate.yaml`. The output is reviewable and is not applied automatically.
4. Optional paired `--rdt-source-pvc APPROVED_SNAPSHOT --rdt-approval-ref OWNER_REFERENCE` mounts `/data/rdt` read-only in Secure only. Database permissions require separate provisioning.
5. Establish file/history ownership and save rollback before migration. Never clone shared histories into every user. Do not run two DSH writers against one state directory during image replacement.
6. Test candidate login/logout, fixed user routing, anonymous/cross-user denial, terminal, WebSocket, tools, attachments, restart/persistence, source denial, egress and approved package installation before ingress cutover.
7. Read back deployed image, effective profiles and actual affected behavior. Preserve rollback and record remaining limitations.

The private-runtime generator now preserves the central workspace claim with distinct `dsh/private/<identity-hash>/secure` subpaths instead of silently allocating local workspaces. Pre-create and review those directories administratively before deploying private runtimes. Source tests pass; Production still uses the shared environment pools, not private per-user runtimes.

The existing main `dsh`, `dsh-user2` and `dsh3` are legacy workloads with different storage/network configurations. They must be explicitly included or excluded from pilot scope; do not assume the new policies protect them.

## Model limits and performance

The inference server has a 1,048,576-token ceiling with memory fraction 0.90, chunked prefill 1,024, maximum prefill 2,048 and concurrency 16. An earlier million-token backend test passed. The newer scheduler improved short-request completion during approximately 133K prefill from 32–34 seconds to 0.59–1.47 seconds in controlled tests, at an observed increase in long-request completion from about 36 to 39–40 seconds.

DSH and LiteLLM still enforce 131,072 total tokens, 8,192 output and compaction near 98,304. End-to-end 1M and sustained throughput are not established. See [context trial history](docs/CONTEXT_OPTIMIZATION_20261015.md) and [scheduling evidence](docs/SCHEDULING_FAIRNESS_20261015.md).

## Official DSH and regression-safe maintenance

Official upstream is a plugin-based developer preview. Our repository contains deployment/authentication/configuration overlays, not a fully synchronized source fork. The inspected official master is `571902028a75c64c1d767f4ae5fd099485f0ddf0`; newer inspected tag is `dsh-v0.2.1-alpha.3`. Our package remains rc.2. No upstream upgrade was deployed in this documentation update.

The [feature comparison and pinned sources](docs/DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.md#official-upstream-comparison) explain Web tasks, model configuration, authentication, public URL support, credential precedence, sessions, storage and overlay risks. In particular, the legacy `isLoopbackHostname` bypass broadens a trust check, and missing-image placeholders do not recover original evidence. The client-helper override alone does not prove the server Host fence is disabled. These require explicit review rather than automatic reapplication.

Prefer supported configuration/plugins; fail on changed patch targets. Candidate upgrades must preserve old state and pass auth, Host/Origin, session/attachment, credential, tool, WebSocket, network/data isolation, restart and restore gates. See [upstream synchronization procedure](docs/UPSTREAM_SYNC_AND_INTERNET_POLICY.md).

## Evidence and closure

At **20:39 ICT, 15 October 2026**, gateway, Secure and Internet all run build **62702**, image `sha256:96be6e7fad0a1d456484bacfed45612c3d3ba95290a9f59a03eb612d50a4efc1`, built from Azure source `3fa74b72eaad7d7dd1e0986dd07a176f45ab2153`. Fresh login/logout, held sessions across backend restarts, actual catalog API and internal inference passed in both pools. Secure retained 80 listed histories and 2,732 checked regular files with zero content failures; Internet retained two controlled markers (its real history list was empty). [Live readback and test results](docs/context-evidence/runtime-rollout-live-20261015.json) and the [rollout walkthrough](docs/DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.md) record exact scope and failed verification attempts.

Pools now use actual application startup/readiness/liveness checks and Recreate to prevent concurrent state writers. Gateway cookie caching detects rotated backend launch tokens; cookies default Secure. No tested application regression required rollback. Original deployment specs and coherent local archive PVCs remain available; full archive restore and intentional rollback were not exercised. Terminal HTTP pages passed, but interactive terminal/WebSocket behavior was not retested. New documentation/operator-script commits are not the image-source commit.

Registration is closed and active catalogs are internal-only. Named-user isolation, approved RDT access and continuous central history/state synchronization remain pending; the actual DA_WORKSPACE workspace mount is restored. The local snapshots do not protect against node loss. Owner approval and assessor sign-off remain separate from code completion.


## Central workspace correction verified — 15 October 2026, 21:32 ICT

Both mount directions were tested through an independent peer pod, followed by a real Secure restart and fresh/held login/logout checks. Secure still lists 80 histories. Reconciliation verified all 2,651 local workspace files and retained central-only content. A coherent history baseline was restored into scratch storage and 29,067 extracted files checked. The first validator failed on an unsupported Python API and triggered an actual mount rollback; the portable validator and retry passed. This is not a full restored-runtime boot or continuous history-sync claim. See [live evidence](docs/context-evidence/central-workspace-live-20261015.json).


## Session storage and compatibility review

The original folder name verified in the supplied transcript is `dsh_storage`, not `dsh_volume`. Secure workspace is now mounted on CIFS, while active sessions/history remain in its local `/state`; Internet uses separate local workspace/state and cannot mount the protected share. Historical `dsh_storage/sessions` on CIFS is not a live mirror. A read-only API/path check found 43 of 80 stored Secure sessions still reference inaccessible `/root/...` cwd values; the other 37 use readable `/workspace/...` paths. History listing and restart checks do not establish full tool resumption for those legacy records. See [review evidence](docs/context-evidence/environment-session-storage-review-20261015.json).
