# DSH — Controlling Three Security Risks

DSH controls three risks: external leakage, damage or excessive access, and exposure of results. The Harness, its tools and generated code are treated as automation that can make mistakes. The application therefore enforces boundaries through network policy, private execution, scoped storage and authenticated routes rather than relying on prompt instructions.

**Scope conclusion:** the agreed DSH-controlled measures described below are implemented, with their defined acceptance checks completed in the recorded deployment review. No unresolved local failure was identified by those checks. This is completion of the reviewed application scope, not a guarantee against every attack, mistake or future regression. External dependencies and deliberate scope limits are consolidated in the final section; they are not presented as unfinished DSH implementation.

This report explains the design and responsibility boundaries. Detailed measurements, test histories and recovery procedures remain in separate operational documents. This revision does not perform a new deployment or security test.

## 1 Prevent external leakage

### Control objective

Prevent unauthorized public connections from the No Internet execution environment while retaining only the internal services required for work. Internet access is provided through a separate environment for dependency preparation, with no automatic transfer of protected data.

### Separate execution and network boundaries

No Internet / Internal is the default login choice. Each main user has a private runtime for this environment and a different private Internet runtime. Authentication fixes the user/environment route for the login session. Switching environments requires logout and a new login; a submitted username, routing header or changed selection cannot choose another user's backend.

No Internet has a restricted outbound network policy. Its approved paths include internal inference, controlled DNS and permitted authentication or job-submission services. Public-domain and direct-IP connectivity are restricted at the network layer, including commands launched from the terminal. The runtime has no Kubernetes management token with which to change its own policy.

The Internet environment has separate compute, workspace, histories and credentials. It does not mount protected No Internet working data. Its public connectivity supports dependency preparation; it is not an alternate processing route for protected prompts, tickets, datasets or reports. The shared internal gateway and inference services do not merge user workspaces. This architecture provides restricted egress, rather than a strict air gap.

The gateway, LiteLLM, local model providers and supporting database have their own destination restrictions. Filtered internal DNS serves approved internal names rather than forwarding arbitrary public lookups. Supplied model clients use internal LiteLLM with model-scoped credentials and operator-owned configuration; external model fallback is disabled for the managed route. Client configuration complements infrastructure enforcement and does not replace it.

### Transfer dependencies without sharing protected workspaces

The Internet environment downloads package artifacts into an incoming area. An operator reviews their source, version and expected hashes. A controlled promotion process verifies selected bytes and places approved artifacts in a separate cache. No Internet mounts that cache read-only and installs without a public package index.

Internet cannot directly install into the protected runtime or modify its workspace. Prompts, datasets, credentials, histories and reports are not dependency artifacts and must not use this transfer path. Hash verification establishes artifact integrity; package approval remains necessary because an intact package can still contain harmful code.

```mermaid
flowchart TB
 U[Named user] --> G[Authenticated environment routing]
 G --> S[No Internet - private execution and data]
 G --> I[Internet - separate dependency staging]
 S --> M[Internal LiteLLM]
 M --> LM[Local model and embedding providers]
 LM --> LE[Public egress denied]
 DB --> LE
 M --> DB[Approved internal database]
 G --> DNS[Filtered internal DNS]
 M --> DNS
 S --> B[Network layer blocks public destinations]
 I --> P[Incoming packages]
 P --> V[Operator review and hash verification]
 V --> C[Approved read-only cache]
 C --> S
 X[Legacy hostname] --> Y[Owner-only authentication]
 Y --> Z[Legacy Internet workload]
 Z --> L[Allowed Livy endpoint]
 S --> L[Allowed Livy endpoint]
 L --> R[Remote Spark drivers and executors]
 R --> E[Remote platform network policy]
 classDef exposure fill:#7f1d1d,stroke:#f87171,color:#ffffff
 class E exposure
```

### Keep environment choices explicit

Legacy DSH2 and DSH3 are owner-only Internet-capable instances. They do not offer a misleading No Internet choice. Their authenticated proxies and ingress restrictions prevent direct peer access, while retaining their intended internal inference and permitted service connections. Protected offline work uses the designated No Internet environment.

An internal connection to another platform does not grant administration of that platform. If a submitted command executes remotely, that platform applies its own permissions and network rules; this responsibility is separated in the final section.

## 2 Prevent damage or excessive access

### Control objective

Contain local execution and prevent peer or administrative access beyond the selected user's environment. Preserve existing permissions on connected platforms instead of silently granting broader access or imposing an unrequested replacement authorization policy.

### Run tools within a private, restricted workload

Each main user/environment has a separate execution process with bounded workspace, session, attachment and credential mounts. Isolation is enforced through the workload and mounted scope, rather than merely choosing different folders in one shared process. Broad parent directories containing other users' data and host-management interfaces are not exposed to ordinary execution.

The workloads execute as non-root, disable privilege escalation, drop Linux capabilities, use RuntimeDefault seccomp and have no mounted Kubernetes management token. CPU and memory limits constrain local resource use. Legacy instances similarly use restricted non-root execution with a designated owner account.

DSH, Claude Code and TrueForge inherit the selected runtime's identity, mounts and network policy. Installing a tool does not grant a privileged container, host socket or another user's credentials. TrueForge's optional nested sandbox remains disabled under the current restrictions; its absence is an agreed capability limit, not a reason to weaken the container boundary.

### Preserve private work and bounded write access

Protected working files and durable histories use bounded central CIFS paths. Internet workspaces and histories remain separate. Credentials and profiles remain in their designated private state locations, while approved dependency artifacts are read-only. Generated outputs belong in the user's designated writable working area.

Existing histories and files retain their ownership. An explicitly authorized support copy is independent and does not reassign the source, expose a shared parent directory or establish ongoing synchronization. Persistence across runtime replacement is part of the application design; independent recovery from authorized or accidental deletion is a separate storage-service responsibility.

### Use connected services under existing authorization

Datalake connections authenticate with the applicable Kerberos principal. DSH does not expand that principal's permissions, grant administration of the datalake or redefine its dataset scope. Submitted commands remain subject to that platform's authorization and execution controls. Existing personal and system-account entitlements are preserved as agreed.

A generated command can still make a mistake within permissions already granted. Tasks should therefore separate original inputs from outputs and review destructive operations where appropriate. If a particular exercise requires sandbox-only or read-only access, the relevant platform owner provisions that entitlement; it is not a universal missing DSH feature.

```mermaid
flowchart TB
 U[Named user] --> P[Main private non-root runtime]
 P --> W[Own writable workspace and results]
 P --> C[Private credential cache]
 C --> K[Kerberos execution identity]
 K --> A[Effective datalake authorization]
 A --> D[Permitted datasets or sandbox]
 A --> N[Existing platform permissions]
 P --> Q[CPU and memory limits]
 D --> O[Task-designated result location]
 classDef pending fill:#78350f,stroke:#fbbf24,color:#ffffff
 class N pending
```

### Bound shared resources

The inference route counts the complete request, reserves output capacity and controls admission of expensive work. Long requests use bounded waiting and an explicit busy response while shorter work remains schedulable. This manages shared capacity; it does not guarantee a response time or change data authorization. Local process limits and shared inference scheduling are DSH controls; remote job queues remain under the platform that executes those jobs.

## 3 Keep results contained

### Control objective

Keep histories, reports, files, attachments and terminal access within authorized user routes. Separate operational oversight from automatic access to user content.

### Authenticate access and bind it to private storage

The gateway admits provisioned named accounts, disables self-registration and binds each authenticated user to the assigned runtime. Reports, files, attachments and terminal WebSockets use the authenticated boundary. Server-side identity and route checks reject forged roles, peer-runtime selection and direct bypass paths.

Each user/environment has separate working files and history storage. Switching environments does not automatically transfer content or credentials. Logout invalidates the gateway session. Legacy instances admit only their designated owners; shared guest and cross-account logins are disabled.

Account stores use salted scrypt password records and bounded verification. Authentication records are stored outside execution workspaces, with protected account volumes and operator-only recovery material. Supplied bootstrap configuration does not create factory-password accounts. Users can change passwords through the authenticated flow; startup does not overwrite a changed password.

### Centralize oversight without merging user content

The admin-only dashboard combines operational information and access events. Administrative visibility does not automatically grant access to another user's conversations or files. Any authorized support copy remains in a separate private store and preserves the original owner's records.

Access auditing records relevant events, user, environment and time outside execution workspaces. It excludes passwords, Kerberos tickets and conversation bodies. Legacy exporters read only their access-log scope and write a bounded central projection. Execution users do not receive the account or audit stores. Required gateway auditing fails closed when an access event cannot be persisted.

The dashboard distinguishes timestamped infrastructure snapshots from current gateway information. Refreshing a snapshot is not a new infrastructure test. Access logs support accountability; a full command recorder, conversation archive and independent audit-retention service are separate capabilities.

```mermaid
flowchart TB
 U[Named user] --> G[Authenticated gateway]
 G --> R[Fixed private runtime]
 R --> F[Own files - reports - history]
 X[Other user] --> N[Peer routes and files denied]
 A[Admin] --> D[Admin-only dashboard and access audit]
 A --> P[Own private runtime]
 LA[Protected legacy access logs] --> EX[Read-only log exporter]
 EX --> CP[Bounded central access projection]
 CP --> D
 F --> B[Authorized browser access]
 B --> E[Manual copying requires endpoint controls]
 classDef boundary fill:#78350f,stroke:#fbbf24,color:#ffffff
 class E boundary
```

### Deliver generated results through the same boundary

Working reports, charts, temporary files and generated applications remain in the private environment. Server-side file access uses the authenticated identity rather than a submitted owner name or arbitrary filesystem path. Exposing a new application requires the same authenticated proxy and user-bound storage; it does not justify a new public bypass route.

The managed workflow does not automatically publish protected results externally. The No Internet environment's network policy blocks direct public transmission from its execution runtime. Internet-capable tools must not be represented as having the same offline restriction. Authorized viewing and downloading are normal application functions; additional restrictions on what a person copies require an explicit handling policy and endpoint controls.

## External dependencies and agreed scope limits

The following items define responsibility and intended use. They do not constitute outstanding implementation of the local DSH controls, and categorizing them here does not make their exposure disappear.

| Boundary | Responsibility and agreed treatment |
|---|---|
| Remote Livy/Spark execution | The datalake platform controls its drivers, executors, job limits and outbound network. DSH restricts its local submission path but does not administer those machines. Livy/Spark remains available under the previously accepted remote-egress exception. Restricted local egress must not be described as a guarantee about a remote worker. |
| Dataset and sandbox authorization | The platform's existing Kerberos/AD and data permissions remain authoritative. No DSH-imposed universal read-only policy is required. A sandbox-only or read-only entitlement is confirmed by its owner when that specific usage claim is needed. |
| Authorized browser handling | Viewing, copying and downloading by an authorized person are distinct from peer access or unauthorized publication. Device restrictions, managed browsers or DLP apply only where required by the organization's handling policy. |
| Identity lifecycle | Corporate SSO/MFA and organization-wide recovery policies are outside the agreed local-account deployment. Owner-managed password changes are provided. By explicit decision, automatic operator rotation is not scheduled; a known password remains usable until changed. This is a retained operational choice, not evidence that hashing neutralizes a known password. |
| Storage recovery and infrastructure administration | Central storage provides persistence. Storage-server ACL administration, independent backups and disaster recovery belong to that service. Cluster, host and storage administrators remain trusted privileged operators. |
| Audit-service extensions | Current central access logging and dashboard oversight are included. Complete command/body capture, remote-job correlation and independently retained audit archives are additional integrations requiring a defined policy; they are not claimed as current features. |
| Deliberately Internet-capable environments | Internet staging and the legacy Internet instances retain their intended public connectivity. They are not protected No Internet environments and must not be used as an automatic bridge for protected content. |

**Completion rule:** the reviewed DSH application controls are implemented and their recorded acceptance checks are complete. Keep them maintained through controlled upgrades and regression checks. A new requirement, failed test or discovered bypass reopens the affected local item; an external dependency remains assigned to its owner rather than silently being declared fixed. This report introduces no new data access, mandatory datalake permission change, credential rotation or platform restriction.
