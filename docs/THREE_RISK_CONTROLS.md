# DSH — Controlling Three Security Risks

DSH provides private AI workspaces for code, documents and analysis. The deployment design controls three risks: unauthorized external transmission, damage or excessive access, and exposure of results to the wrong people. Infrastructure, execution identities, storage permissions and authenticated routes enforce the boundaries. Model instructions describe the task; they do not replace enforcement.

## 1 Prevent external leakage

Make No Internet the default environment. Give each user a separate Internet environment for dependency preparation, with different compute, workspace, history and credential mounts. Pin the authenticated session to its assigned user and environment.

Enforce destination restrictions on execution workers, the gateway, inference services and supporting databases. Allow only required internal services and a controlled resolver. Disable external model fallback on the managed inference route. Test public-domain and direct-IP attempts from the actual executing workloads; ordinary DNS access or a browser preference is not an egress boundary.

Transfer approved package artifacts through incoming, review and read-only approved-cache areas. Do not share writable protected workspaces with Internet staging. Verify artifact hashes and review package provenance; integrity does not establish that a package is harmless.

An internal service connection remains connected, so describe this as restricted egress rather than a strict air gap. A submitted job executing on another platform needs that platform's own outbound controls.

## 2 Prevent damage or excessive access

Use one restricted non-root execution workload per user and environment, with only its own workspace, history and credentials mounted. Disable privilege escalation, drop capabilities, apply a restrictive security context and avoid management tokens, host sockets and host paths. Share the model service without sharing user execution or storage.

Enforce CPU, memory and storage budgets where the work runs. Bound costly model admission and waiting independently of account authorization. A private writable workspace remains writable by its owner and generated code: where originals must not change, mount approved inputs read-only and place results in a separate writable working area.

Connected services enforce their own execution identity and existing permissions. A DSH login does not grant database or datalake rights. Use a sandbox-scoped or read-only entitlement when the task requires one. Preserve private credentials; never place passwords, tickets or API keys in prompts, generated reports or public configuration.

Persist durable files and history on appropriately scoped storage. Validate permissions and restart persistence. Central storage is persistence; independent backups and deletion recovery remain storage operations.

## 3 Keep results contained

Authenticate file, history, attachment, terminal and notebook routes, then authorize them against the server-side identity and assigned runtime. Reject peer selection, forged owner headers and direct bypass paths. Self-service signup must assign an exclusive prepared workspace and refuse safely when capacity is exhausted; Internet permission is a separate administrator grant.

Keep reports private by default. Register an application through an explicit mapping and choose its audience deliberately. Private local applications remain user/environment-bound. A Public mapping publishes that application's route, not its owner's whole workspace. Destination authentication remains independent. Protect built-in terminals and notebooks from Public publication.

Keep account stores and access logs outside execution mounts. Use salted password records and a protected password-change flow. Provide an administrator dashboard for access, capacity and application management without automatically transferring ownership of private content.

Audit bounded access metadata without recording credentials or conversation bodies. Display freshness for saved operational snapshots. Access logs are not a complete command ledger or GPU monitor. An authorized browser can display and download results; additional copying restrictions require an agreed handling policy and endpoint controls.

## Responsibilities on connected systems

| Boundary | Responsible control |
|---|---|
| Remote jobs | Remote platform identity, permissions, network restrictions, quotas and cancellation |
| Protected inputs | Data/storage owner provisions the required read-only or sandbox entitlement |
| Browser handling | Organization defines recipients, permitted downloads and any required endpoint controls |
| Identity lifecycle | Operator manages membership, recovery, exposed-password changes and optional SSO/MFA |
| Recovery | Storage owner manages server ACLs, independent backups and restore procedures |
| Inference qualification | Operator tests the exact model/runtime profile, concurrency, cancellation and memory stability |

## Setup, use and technical appendices

Follow the [complete installation guide](INSTALL.md), then the [acceptance checks](ACCEPTANCE.md). Use the [application proxy guide](APP_PROXY.md) for routes and destination boundaries. Consult [managed-client compatibility](LIVE_CLIENT_COMPATIBILITY.md) for existing-workspace launch scope.

GPU setup is maintained in [gpu-stack](../gpu-stack/README.md). [Context configuration](CONTEXT_1M.md) explains counting, output reserve and admission. Treat any recorded GPU result as specific to its checkpoint, runtime, input size and concurrency: configured capacity, analytical accuracy, cold preparation and streaming speed are distinct measurements.
