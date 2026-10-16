# DSH — Private Execution Environments and Kerberos Datalake Access

DSH provides local login, **No Internet / Internal (default)** and **Internet** environments, private per-user execution/storage, central audit, internal LiteLLM and shared four-H100 inference. RDT access uses **Kerberos kinit → Livy/Spark → Hive/HDFS authorization**. DA_WORKSPACE stores projects, results and history; it does not grant RDT access. Local DSH accounts are not AD/SSO accounts.

Read the English [security and architecture walkthrough](docs/DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.html) and [source report](docs/DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.md). HTML embeds this README and saved evidence with SMP EDA diagram zoom, fullscreen and SVG/PNG export.

## Features, design reasons and live status — 16 October 2026

| Feature | Reason | Verified scope |
|---|---|---|
| No Internet default | Restrict Harness, generated code and local subprocess egress | Nine workers tested: public domains/direct IP/DNS denied; allowlisted internal inference, KDC and Livy reachable |
| Separate Internet environment | Prepare dependencies without mounting protected data | Nine workers reach registries but cannot reach KDC, Livy or unrelated private services |
| Per-user runtime and state | Prevent shared-process/file/history exposure | Eight non-admin accounts × two environments deployed; admin retains original two runtimes |
| DA_WORKSPACE persistence | Preserve original mounted central storage design | Private Secure CIFS subpaths; direct durable session/attachment mounts |
| Kerberos client | Authenticate separately to the datalake | Tools/private ticket cache in replacement image; no AD login or data permission granted |
| Restricted inference credentials | Avoid exposing LiteLLM management authority to generated code | Exact inference succeeds; key/model management returns 403 |
| Admin dashboard/audit | Central visibility without sharing conversation content | Admin-only summary and fixed-schema access audit; ordinary/forged-role requests denied |
| Approved package cache | Supply offline dependencies without writable workspace sharing | Incoming → operator review/hash promotion → read-only Approved; empty-cache canaries are not package installation acceptance |
| Shared model | Use the existing single-node GPUs efficiently | Backend 1M ceiling; DSH/LiteLLM user guardrail 128K; request cap 16 |

The remaining end-to-end RDT gaps are actual AD/Livy/Spark identity and read-only Hive/HDFS permission tests, remote executor egress, and owner-approved report/export rules. A synthetic read-only filesystem test does not establish those controls. Legacy DSH2/DSH3 are older root/Internet instances, outside this private pilot acceptance.

## Architecture and storage

Login pins one identity to one environment until logout. Private workspaces, sessions, attachments, credentials and launch tokens are separate. Inference and reviewed dependency artifacts are shared. Internet cannot install directly into No Internet. No Internet is **restricted egress, not an air gap**, because required internal services remain connected.

The share remains `\\bot.or.th\cfs\FILESERV\DA_WORKSPACE\workstation`. Historical directory name is `dsh_storage`, not `dsh_volume`.

| Content | Private No Internet | Private Internet |
|---|---|---|
| Workspace | CIFS `dsh/private/<identity>/secure` | Separate local PVC |
| Sessions/attachments/storages/workspaces/logs | CIFS `dsh/private/<identity>/state/<directory>` | Separate local state PVC |
| Credentials/configuration/Kerberos cache | Private local `/state`, ticket cache `/state/kerberos/ccache` | Separate private state |
| Dependencies | Approved read-only cache | Writable Incoming |

Admin retains the original central `dsh` / `dsh/dsh_storage` trees and all 80 histories. Admin's broad legacy mount is a trusted-admin exception; ordinary runtimes cannot mount its root. Gateway audit is central `dsh-admin-audit`, outside execution mounts. Direct CIFS mounts need no continuous copy loop. PVC persistence is not backup/disaster recovery.

All 80 histories in 82 files remain unchanged, aggregate SHA256 `7bb4aa235893e12b0bf545a4f87e00a3a6df2a656e33acdb5231c8def460c317`. Actual process replacements preserved workspace/attachment markers. No histories were copied into non-admin accounts.

## Admin access and audit

Open [Admin overview](https://dsh.aiportal.bot.or.th/admin) as existing `admin`, or use its navigation link. Registration is disabled. `DSH_ADMIN_USERS` is an operator allowlist, not a client role selector. Gateway source overlay SHA256 is `b34ee162ec9b29e83602fdf7e0785188c1935ce3a95eb49e43f7dda482366a94`.

The dashboard combines live gateway counts/routing/audit with a timestamped infrastructure snapshot; Refresh does not run infrastructure probes. Audit fields are time/event/user/environment, without passwords, tickets, prompts or conversation text. Rotation retains archives; capacity exhaustion refuses new runtime/login access until approved archival. It is not a complete command transcript or tamper-proof SIEM. The gateway has no Kubernetes API token.

## Setup, changes and rollback

1. Build/test via Azure pipeline, pin an immutable runtime digest and test it in a disposable namespace. Build 62743 uses source `4b90c846ead7098433173a18046105b179744737`, image `dsoreg-sm1-p1.bot.or.th/da-gpu-server/dsh-runtime@sha256:c10f792b1516813fb2d5c4b4de0bfe816931dfcf71caeab8cd161cb13c5a8ca6`. All 18 runtime replacements and final gateway access checks passed; see [actual live acceptance](docs/context-evidence/kerberos-runtime-live-62743.json). Build success alone is not Production acceptance.
2. Provision protected Secrets, auth state and the CIFS claim with explicit UID/GID mapping. Never commit credentials, keytabs, tickets, PATs or kubeconfigs.
3. Review `k8s/dsh-internal-dns.yaml` and `k8s/dsh-egress-policies.yaml` against actual pod-side DNS, KDC/Livy addresses and CNI behavior. Exact allowlists must be updated deliberately when endpoints change. Internet permits public registries, not datalake access.
4. Use `scripts/generate_user_runtimes.py` for reviewed private-user manifests and identity-specific CIFS subpaths. It does not infer history ownership or migrate existing records. The existing private cutover is already complete; do not blindly rerun initial provisioning against live users. Preserve admin routes, source overlay, audit mount and infrastructure snapshot.
5. Run non-root without privilege escalation/capabilities/service-account token. Private frontends request 250m CPU/1Gi RAM with 4CPU/8Gi limits; creating a runtime does not allocate another GPU model.
6. Authenticate to the datalake only with approved Kerberos identities. A private cache is not a read-only grant. Test Livy/Spark identity, Hive/HDFS allowed reads and denied source modifications/unrelated reads at the backend; include remote executor egress. DA_WORKSPACE is not that authorization control.
7. Sequentially replace runtimes only after a matching image canary. `scripts/rollout_kerberos_runtime.py` snapshots specs and checks imageID, persistent markers, Kerberos client/cache and actual gateway behavior. On regression restore specifications without overwriting newer data. Preserve rollback originals and reconcile storage before any mount reversal.

Optional read-only filesystem fixtures are explicitly named synthetic fixtures; they are unrelated to real RDT. Historical artifacts retain their original `/data/rdt` fixture naming with that limitation stated in the report.

## Evidence and operational lessons

See [private Production routing](docs/context-evidence/private-routing-live-20261016.json), [all-worker network tests](docs/context-evidence/internal-network-live-20261016.json), [image canary](docs/context-evidence/kerberos-image-canary-62743.json) and the report's trial table. It records CPU oversubscription, credential replacement rollback/retry, split DNS, RKE2 discovery and the cache-mode verification rollback. Tests distinguish saved snapshots, source changes, built images and live behavior. No real AD authentication or RDT write probe was performed.

## Context, speed and concurrency

Backend: context 1,048,576; memory fraction 0.90; running-request cap 16; prefill chunk 1,024; maximum prefill 2,048; mixed prefill/decode; decode interval four. The V2 overlay reserves up to 512 prefill tokens for short uncached tails while preserving long progress. It rejects an unexpected upstream scheduler source hash.

DSH web profiles and LiteLLM retain 131,072 total tokens, 8,192 maximum output and a 256-token proxy reserve. Automatic compaction is configured at 75%, approximately 98,304 tokens. Compaction success for every historical session is not established.

Recorded V2 mixed-load tests completed short requests in 0.59–1.47 seconds during approximately 133K input work. A later two-request short test verified exact output and about 34–35 output tokens/second per request including request elapsed time. These are bounded samples, not an SLA or sustained benchmark. The earlier successful near-1M test belongs to the prior scheduling profile; it is not fresh proof of end-to-end DSH 1M, two simultaneous 1M sessions or V2 near-1M fairness. See [trial history](docs/CONTEXT_OPTIMIZATION_20261015.md) and [scheduling evidence](docs/SCHEDULING_FAIRNESS_20261015.md).

## Upstream synchronization and rollback

This repository maintains deployment/authentication/configuration overlays, not a fully synchronized official source fork. The previously inspected official master was `571902028a75c64c1d767f4ae5fd099485f0ddf0`; inspected tag `dsh-v0.2.1-alpha.3`; deployed package remains rc.2. These are dated observations, not a fresh upstream check. No package upgrade is implied by the storage deployment.

Rebase overlays onto a candidate pinned release, fail closed on changed patch targets, and test auth/Host/Origin, HTTP/WebSocket terminal, sessions, attachments, tools, network isolation, restart and restore before switching. Keep the installed image and coherent old state available for rollback. See [upstream procedure](docs/UPSTREAM_SYNC_AND_INTERNET_POLICY.md).

The same reviewed DSH tree is mirrored under `GPU_server/deployment/vllm/dsh-environments`; GPU model and scheduling sources remain in GPU_server. Historical reports stay dated and preserved. Source completion, live behavior, scan results and owner/assessor acceptance are separate claims.
