# DSH — Controlling Three Security Risks

DSH provides private AI workspaces for code, documents and analysis. The deployment design controls three risks: unauthorized external transmission, damage or excessive access, and exposure of results to the wrong people. Infrastructure, execution identities, storage permissions and authenticated routes enforce the boundaries. Model instructions describe the task; they do not replace enforcement.

## 1 Prevent external leakage

Make No Internet the default environment. Give each user a separate Internet environment for dependency preparation, with different compute, workspace, history and credential mounts. Pin the authenticated session to its assigned user and environment.

Enforce destination restrictions on execution workers, the gateway, inference services and supporting databases. Allow only required internal services and a controlled resolver. Disable external model fallback on the managed inference route. Test public-domain and direct-IP attempts from the actual executing workloads; ordinary DNS access or a browser preference is not an egress boundary.

Transfer approved package artifacts through incoming, review and read-only approved-cache areas. Do not share writable protected workspaces with Internet staging. Verify artifact hashes and review package provenance; integrity does not establish that a package is harmless.

For supported pinned Python wheels, **My Python environments** provides a self-service path after the administrator grants the account Internet access. An isolated Internet job downloads artifacts; validation and offline installation create a new private No Internet environment and Jupyter kernel without replacing existing environments. Source builds, direct URLs and startup `.pth` hooks require operator review. This path does not share protected workspaces or require manual promotion of every wheel request. See the [user workflow](DSH_USER_MANUAL.md#5-prepare-packages-for-no-internet-work).

An internal service connection remains connected, so describe this as restricted egress rather than a strict air gap. A submitted job executing on another platform needs that platform's own outbound controls.

## 2 Prevent damage or excessive access

Use one restricted non-root execution workload per user and environment, with only its own workspace, history and credentials mounted. Disable privilege escalation, drop capabilities, apply a restrictive security context and avoid management tokens, host sockets and host paths. Share the model service without sharing user execution or storage.

Enforce CPU, memory and storage budgets where the work runs. Bound costly model admission and waiting independently of account authorization. A private writable workspace remains writable by its owner and generated code: where originals must not change, mount approved inputs read-only and place results in a separate writable working area.

Connected services enforce their own execution identity and existing permissions. A DSH login does not grant database or datalake rights. Use a sandbox-scoped or read-only entitlement when the task requires one. Preserve private credentials; never place passwords, tickets or API keys in prompts, generated reports or public configuration.

Persist durable files and history on appropriately scoped storage. Validate permissions and restart persistence. Central storage is persistence; independent backups and deletion recovery remain storage operations.

## 3 Keep results contained

Authenticate file, history, attachment, terminal and notebook routes, then authorize them against the server-side identity and assigned runtime. Reject peer selection, forged owner headers and direct bypass paths. Self-service signup must assign an exclusive prepared workspace and refuse safely when capacity is exhausted; Internet permission is a separate administrator grant.

Keep reports private by default. Register an application through an explicit mapping and choose its audience deliberately. Private local applications remain user/environment-bound. A Public mapping publishes that application's route, not its owner's whole workspace. Destination authentication remains independent. Protect built-in terminals and notebooks from Public publication. An owner may explicitly share an ordinary local application with selected enabled DSH accounts, or explicitly all enabled accounts, while its host, port and environment stay fixed. JupyterLab and terminals remain owner-only, including authenticated sharing. Sharing does not grant workspace, history or management access; the application must control the data and write actions it exposes. See [authenticated sharing boundaries](AUTHENTICATED_APP_SHARING.html).

Keep account stores and access logs outside execution mounts. Use salted password records and a protected password-change flow. Provide an administrator dashboard for access, capacity and application management without automatically transferring ownership of private content.

Audit bounded access metadata without recording credentials or conversation bodies. Display freshness for saved operational snapshots. Access logs are not a complete command ledger or GPU monitor. An authorized browser can display and download results; additional copying restrictions require an agreed handling policy and endpoint controls.


## How the three controls relate to OWASP Agentic Top 10 (2026)

This is a mapping of documented DSH controls to OWASP risks, not a certification or a new security test. Containment reduces possible harm; it does not prove that a model will reject malicious instructions or that every workflow is safe. Coverage below is partial unless a specific saved acceptance test establishes the stated boundary.

Control 1 limits unauthorized network transmission. Control 2 limits execution and access. Control 3 keeps files and outputs behind explicit authorization. Apply these controls together; review the residual risks below for each pilot.

| OWASP risk | Documented overlap and remaining test |
| --- | --- |
| ASI01 — Agent Goal Hijack | Execution and network containment limit consequences; no explicit goal-integrity/injection test matrix. |
| ASI02 — Tool Misuse and Exploitation | Restricted workloads and existing service permissions; no complete tool/argument approval assessment. |
| ASI03 — Identity and Privilege Abuse | Private identities, routes and mounts; remote entitlements and identity lifecycle remain separately owned. |
| ASI04 — Agentic Supply Chain Vulnerabilities | Pinned dependency transfer, offline validation and review of source builds/hooks; no full agent/MCP provenance assessment. |
| ASI05 — Unexpected Code Execution | Non-root execution, limited mounts/capabilities and restricted egress constrain execution; do not prevent all hostile code in writable scope. |
| ASI06 — Memory and Context Poisoning | Private history isolation is described; persisted malicious context, provenance and safe reset are not explicitly assessed. |
| ASI07 — Insecure Inter-Agent Communication | User routing does not establish authenticated agent messages, replay protection or delegated authority. |
| ASI08 — Cascading Failures | Resource admission and local limits; downstream failure propagation, circuit breaking and end-to-end recovery remain workflow-specific. |
| ASI09 — Human-Agent Trust Exploitation | Explicit sharing and handling responsibilities; misleading output and meaningful human review require workflow tests. |
| ASI10 — Rogue Agents | Runtime restrictions limit blast radius; autonomous scope drift, detection and containment need explicit tests. |

Practical example: a claims file could contain instructions to send customer data elsewhere. A blocked public connection limits that route, but does not prevent a misleading local report. Use a harmless test file to check the full path: input provenance, permitted tools, saved context, output review and attempted external requests. Test agent messages and downstream jobs separately where used. Record the exact version, expected refusal or containment, actual result and remaining owner action; do not mark a gap closed from a prompt or configuration alone.

Source and attribution: [OWASP GenAI Security Project — OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/), December 2025. Risk names are attributed to OWASP; the DSH mapping and examples are our analysis, not OWASP endorsement. No claim of full compliance is made.

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


## Application audience controls

Application audiences are separate from workspace permissions. The Main gateway checkbox editor offers all authenticated accounts, local accounts, AD / LDAP accounts, selected local users or owner-only. New ordinary apps default to all authenticated users; saved mappings retain their existing audience until explicitly saved. The gateway checks stored identity type, strips platform credentials and revokes active app connections when eligibility changes. JupyterLab and terminals stay owner-only. The editor is deployed on Main DSH; legacy DSH2/DSH3 entrypoints remain owner-only.

<!-- credential-management-design -->

## User-managed credentials

Credential management design: users enter secrets through a dedicated settings form, while the harness receives only aliases. A separate broker checks the owner, workspace, environment, destination and action before using the secret. Consequential actions require bound approval; audit logs exclude secret values. This broker and settings page are planned, not deployed. Read the [credential management design and video supplement](USER_CREDENTIAL_MANAGEMENT.html).
