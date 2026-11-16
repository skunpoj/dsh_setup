# DSH Current Guide

[Terminology: agent, harness and shared platform](HARNESS_TERMINOLOGY.html). Compare agent integration routes while preserving SDK, harness and infrastructure distinctions.

Implementation reference: `b715708e3d0d01113c4fc79751110f2cea086a4e`. One canonical guide; video lessons retain their own source snapshots.

## 1 DSH Current Guide

A guide to main DSH workflows, with site-specific access and storage.

- Main DSH workflows and shared inference
- Three risk controls guide every workflow
- Other sites retain their configured access and storage

Sources: [DSH_USER_MANUAL.md](DSH_USER_MANUAL.md), [DSH_PLATFORM_GUIDE.md](DSH_PLATFORM_GUIDE.md)

## 2 Three risk controls

Workbook anak_tool&risk_ai_draft J1/K1/L1 define policy/human, harness/deterministic and infrastructure/resource controls. M1 is audit across all three. CIA and leakage/damage/result-exposure are risk objectives, not alternative names for the three control layers. PPTX slide 2 separates runtime containment from independent resource authorization within the third layer.


## 3 A bounded task produces a reviewable result

Define inputs, permitted actions and expected evidence before asking the assistant.

- Identify the project and approved files. Start with read-only inspection when the scope is uncertain.
- Keep changes inside the selected project and generated results separate from original inputs.
- Inspect saved outputs and meaningful checks. An AI answer or successful status alone is not acceptance.

Sources: [DSH_USER_MANUAL.md](DSH_USER_MANUAL.md)

## 4 Sign in with the correct identity

Local DSH and corporate AD / LDAP use explicit provider selection.

- Local: use a provisioned account or Create account when private capacity is available. New passwords need at least 12 characters.
- AD / LDAP: use an approved short name, corporate UPN or DOMAIN\username. A Local-name collision is refused.
- New accounts receive private Internal access. Internet needs a separate grant. DSH sign-in does not create a Kerberos ticket.

Sources: [DSH_USER_MANUAL.md](DSH_USER_MANUAL.md), APP_URLS_AND_INGRESS.md (not included in this public source projection)

## 5 Choose the environment for the data

Internal and Internet are separate private environments.

- No Internet / Internal is the normal place for approved internal work. Explicitly approved internal services can remain reachable.
- Internet is for approved public work and dependency preparation. Its workspace, history and credentials remain separate.
- Log out and sign in to change environments. Files are not copied automatically. A remote job follows its own platform policy.

Sources: [DSH_USER_MANUAL.md](DSH_USER_MANUAL.md), MULTI_TENANT_STORAGE_AND_PERSISTENCE.md (not included in this public source projection)

## 6 Four clients share files, not conversations

DSH, Claude Code, Kilo and TrueForge use one selected project within an account and environment.

- Select the same /workspace/<project> in each client. Their current directories are not synchronized automatically.
- The shared platform guide explains storage, network and managed-model conventions. The gateway still enforces permissions.
- Each client keeps its own conversations. Other users and the opposite environment retain separate files, histories and credentials.

Sources: [DSH_USER_MANUAL.md](DSH_USER_MANUAL.md), AUTOMATIC_CLIENT_ACTIVATION.md (repository source)

## 7 Persistence is separate from a running process

Saved work survives a qualified replacement; in-memory state does not.

- Internal /workspace and durable DSH state use account-scoped CIFS subpaths. Internet uses separate private local volumes.
- Credentials and profiles stay in their assigned private state storage. The legacy owner has a separately preserved layout.
- Saved notebooks, files and supported histories persist. Unsaved edits, kernels and unmanaged processes need separate handling. A live share is not a backup.

Sources: MULTI_TENANT_STORAGE_AND_PERSISTENCE.md (not included in this public source projection)

## 8 Verify tools against the intended project

Read, write and readback establish the actual working directory.

- Ask the selected client to read a named source file and quote a relevant section. Confirm the complete path.
- Save a harmless result in the project output folder and read that exact file back in Terminal or Jupyter.
- Use synthetic files for access tests. A folder name or permission label alone does not establish cross-user isolation.

Sources: [DSH_USER_MANUAL.md](DSH_USER_MANUAL.md), AUTOMATIC_CLIENT_ACTIVATION.md (repository source)

## 9 Internal Git does not require public Internet

Network reachability, certificate trust and repository authorization are separate checks.

- Use the operator-approved HTTPS address with TLS verification. A connection timeout occurs before authentication.
- Use your authorized private credential mechanism. Never put a PAT in a clone URL, prompt or notebook.
- Verify the branch, commit and diff before pushing. Repository access grants neither datalake rights nor public network access.

Sources: CORPORATE_GIT_BOOTSTRAP.md (not included in this public source projection), [DSH_USER_MANUAL.md](DSH_USER_MANUAL.md)

## 10 Open Jupyter without interrupting work

Startup state, Internet permission and running notebook memory are separate.

- Open Jupyter in your allowed environment. Repeated Start leaves an already-enabled service and its restart generation unchanged.
- An existing on-demand server keeps running. The supervisor waits for its port; after natural exit, managed startup can take over.
- Stop disables managed startup; Restart replaces the managed process. Save notebooks first: kernel variables and unsaved memory do not persist.

Sources: [JUPYTER_APP_LIFECYCLE.md](JUPYTER_APP_LIFECYCLE.md), [JUPYTER_START_CONTROLS.md](JUPYTER_START_CONTROLS.md), [JUPYTER_AUTOSTART_BACKFILL.md](JUPYTER_AUTOSTART_BACKFILL.md)

## 11 Install supported Python wheels privately

My apps → My Python environments creates a new offline environment after an Internet grant.

- Request exact versions. A separate downloader receives package artifacts without mounting the protected workspace.
- The offline installer verifies wheel hashes and structure, has no network access, and creates a versioned environment and Jupyter kernel.
- Select the displayed kernel or Python path explicitly. Source builds and system packages use the operator-reviewed process. Existing environments remain intact.

Sources: SELF_SERVICE_PACKAGES.md (not included in this public source projection), [DSH_USER_MANUAL.md](DSH_USER_MANUAL.md)

## 12 An app URL, its audience and its process are separate

Saving or sharing a URL does not start an application.

- My applications maps a name to a local port or approved HTTPS target. Sharing an app does not grant workspace access.
- Start leaves an already-enabled service unchanged. New custom service definitions remain stopped until Start; Restart deliberately replaces the managed process.
- Stop disables managed autostart. A pre-existing unmanaged server stays running; enabled services start after replacement only when environment access is allowed.

Sources: [AUTHENTICATED_APP_SHARING.md](AUTHENTICATED_APP_SHARING.md), APP_URLS_AND_INGRESS.md (not included in this public source projection)

## 13 One editable name limit per user

The default remains eight registered names across both environments.

- One alias may have a port in each environment. Its path and hostname count as one name. Disabled names count until removed.
- Lowering the limit preserves existing mappings and blocks new registrations at or above the limit. There are no approval tiers.
- App-name quota, recipient-list size, service limits and inference concurrency are separate. Selected local sharing accepts 1–128 enabled local recipients.

Sources: [AUTHENTICATED_APP_SHARING.md](AUTHENTICATED_APP_SHARING.md), APP_URLS_AND_INGRESS.md (not included in this public source projection)

## 14 Choose the application’s visitor audience

Main DSH supports explicit app sharing. DSH2/DSH3 legacy entrypoints stay owner-only.

- New ordinary authenticated apps default to All authenticated users (local and AD / LDAP). Existing apps keep their saved audience until Save URL.
- Other audiences: All local DSH users, All AD / LDAP users, Selected local DSH users (checkboxes), or Owner only. Select up to 128 distinct enabled local recipients.
- Jupyter (8888), Terminal (7681) and management ports cannot be shared. Public access and the destination application’s authentication are separate policies.

Sources: [AUTHENTICATED_APP_SHARING.md](AUTHENTICATED_APP_SHARING.md), APP_URLS_AND_INGRESS.md (not included in this public source projection)

## 15 Current application entry points

These aliases illustrate different access policies for existing destinations.

- Example public application: https://public-app.example.invalid/ opens the destination without a DSH gate.
- Example protected application: https://protected-app.example.invalid/ accepts enabled DSH accounts. Both aliases reach the same destination.
- Example resource application: https://resource-app.example.invalid/ uses destination-managed authentication. Its SSO may finish at the original application address.

Sources: APP_URLS_AND_INGRESS.md (not included in this public source projection)

## 16 Share an app without sharing a workspace

Use a dedicated application hostname and the intended audience.

- On Main DSH: My applications → ordinary Local application port → Require DSH sign-in. Choose the audience; tick recipients for Selected local DSH users.
- Edit sharing / URL loads saved settings; the name stays locked. Only Save URL applies changes. New application / cancel edit discards unsaved edits.
- Share the approved hostname for one owner, target and environment. Untick and save, narrow the audience, or disable the mapping to revoke access.

Sources: [AUTHENTICATED_APP_SHARING.md](AUTHENTICATED_APP_SHARING.md), APP_URLS_AND_INGRESS.md (not included in this public source projection)

## 17 Directory sign-in preserves identity boundaries

Corporate authentication does not merge users or grant administrator rights.

- The configured verifier uses strict directory certificate trust and bounded requests. Invalid credentials fail closed.
- First sign-in needs the configured account-creation permission. A colliding Local identity is not silently converted.
- The directory subject identifies the account. The AD password is not saved or forwarded as an app credential; Internet remains separately controlled.

Sources: APP_URLS_AND_INGRESS.md (not included in this public source projection), [DSH_USER_MANUAL.md](DSH_USER_MANUAL.md)

## 18 Proxy, redirect, DNS and webhook have distinct roles

The alias can remain visible for proxied traffic; application redirects may navigate elsewhere.

- DNS resolves a hostname. A reverse proxy forwards compatible pages, assets, APIs and WebSockets through the gateway.
- A redirect asks the browser to visit another URL. A webhook delivers an event or action, not ongoing browser traffic.
- SSO, absolute links and framework roots need destination-specific qualification. The RegChat adapter is narrowly scoped to approved aliases.

Sources: APP_URLS_AND_INGRESS.md (not included in this public source projection)

## 19 DSH sharing does not replace app authorization

The shared app retains its own login, permissions and responsibilities.

- DSH checks visitor access to the saved app; the destination may still require its own login. DSH sign-out does not promise destination sign-out.
- Forwarding strips DSH cookies, credentials and caller-supplied identity headers. Application cookies are separate; sharing does not grant the owner’s files or notebook.
- Visitors can use any write actions the app exposes. Do not share a shell, file browser or management proxy through an ordinary port.

Sources: [AUTHENTICATED_APP_SHARING.md](AUTHENTICATED_APP_SHARING.md), APP_URLS_AND_INGRESS.md (not included in this public source projection)

## 20 Recover a browser session without replaying work

Disconnecting the browser does not delete files or automatically stop an agent.

- Where offered, Sign in again uses the same identity and environment. Return to the draft and submit it yourself. Save drafts before reloading an older tab.
- Logout, expiry, account disablement or revocation can close tracked app and terminal connections. They do not undo saved files.
- Use Stop for the active conversation turn. After a network error, inspect the conversation and output before resending the task.

Sources: [DSH_USER_MANUAL.md](DSH_USER_MANUAL.md)

## 21 Client fixes activate at a safe startup boundary

The compatibility layer validates retained assets before restoring missing launch integration.

- New Bash terminals select current retained launchers. Already-running clients keep their loaded code.
- After replacement, the startup plugin checks release fingerprints and private file properties. Legacy persistent-HOME runtimes use a distinct retained-profile path.
- Integrity failures record a bounded failure and leave DSH available. Never weaken fingerprints or restart an active workspace just to refresh guidance.

Sources: AUTOMATIC_CLIENT_ACTIVATION.md (repository source)

## 22 A small complete exercise checks the workflow

Verify an expected result before relying on a larger analysis.

- Create synthetic data in /workspace/<project>. Ask a client to read it and compute a known answer.
- Save the result and inspect it in another tool in the same environment. Compare the actual contents with the known answer.
- For an app, test the intended audience, assets and a real interaction. Preserve exact inputs and resulting evidence without including secrets.

Sources: [DSH_USER_MANUAL.md](DSH_USER_MANUAL.md), [DSH_PLATFORM_GUIDE.md](DSH_PLATFORM_GUIDE.md)

## 23 Access approval and service state are different

Read the label before granting access or restarting a service.

- Internet approval pending: the account is enabled but lacks Internet permission. Account disabled: the account itself is disabled. These require different access decisions.
- Waiting for existing Jupyter: leave its server and notebooks running. Managed startup takes over after the port is released; closing a tab may not stop it.
- Allow Internet does not override Admin Stop. Enabled services start only when access is allowed; stopped services stay stopped after replacement.

Sources: [JUPYTER_APP_LIFECYCLE.md](JUPYTER_APP_LIFECYCLE.md), [JUPYTER_START_CONTROLS.md](JUPYTER_START_CONTROLS.md), [JUPYTER_AUTOSTART_BACKFILL.md](JUPYTER_AUTOSTART_BACKFILL.md)

## 24 Distinguish waiting, recovery and failure

Status labels explain observations; they do not change permissions or processes.

- Recovery retry pending means a managed process failed or exited and is waiting to retry. Startup failed identifies a failed start attempt.
- Status unavailable means missing or stale status. Neither a loading page nor an open port proves a healthy notebook, kernel or saved-file workflow.
- Review the owner, environment, saved definition and fresh supervisor status. Use Start to enable; use Restart only when interruption is intended.

Sources: [JUPYTER_APP_LIFECYCLE.md](JUPYTER_APP_LIFECYCLE.md), [JUPYTER_START_CONTROLS.md](JUPYTER_START_CONTROLS.md), [JUPYTER_AUTOSTART_BACKFILL.md](JUPYTER_AUTOSTART_BACKFILL.md)

## 25 Current guidance

This guide is the canonical workflow.

- A Test success applies to its source, inputs and workflow. It does not certify every application or future model response.

Sources: [COURSE_DELIVERY.md](COURSE_DELIVERY.md), [SLIDE_DOWNLOADS.md](SLIDE_DOWNLOADS.md)

## 26 Operator appendix: platform layers

Gateway routing, worker processes and capacity reconciliation have separate owners.

- Gateway: identity, sessions and routing. Private workers: tools and saved state. Supervisors: approved service startup and lifecycle controls.
- The trimmed Main gateway projects 26 source modules. Its unused planner copy was removed; the corrected capacity planner remains in the controller.
- Packaging and source-only cleanup do not upgrade the base image. Compare the live image plus mounted source; a newer repository commit is not proof of deployment.

Sources: [JUPYTER_APP_LIFECYCLE.md](JUPYTER_APP_LIFECYCLE.md), AUTOMATIC_ACCOUNT_CAPACITY.md (not included in this public source projection), [DSH_PLATFORM_GUIDE.md](DSH_PLATFORM_GUIDE.md)

## 27 Operator appendix: shared routing checks

An unchanged Ingress specification does not prove unchanged shared-controller behavior.

- DNS, certificate coverage and wildcard rules are separate. Exact-host applications retain precedence and reserved names.
- Wildcard certificate registration can affect other services’ HTTP redirects. Qualify the selected dedicated or controller-default TLS mode.
- Check no-follow HTTP, normal HTTPS, original Qdrant calls and WebSockets. Keep certificate verification enabled and retain reviewed recovery evidence.

Sources: APP_URLS_AND_INGRESS.md (not included in this public source projection)

## 28 Operator appendix: document publication

Stage approved content and switch the document edition atomically.

- Preserve the prior manifest, source revision and archive hashes. Add only approved attachment names and retain the existing audience.
- Verify HTTP bytes and a browser download. Import and render the saved file, then check navigation to the canonical edition.
- Compare worker identities, restart counts and existing state before and after publication. Publishing a guide does not authorize worker restarts.

Sources: [COURSE_DELIVERY.md](COURSE_DELIVERY.md), [SLIDE_DOWNLOADS.md](SLIDE_DOWNLOADS.md)

## 29 Use isolated evidence for recovery decisions

Saved files persist; live kernel memory does not.

- Two users and four replacements preserved 12 saved files. Separate disposable tests verified approval → waiting → Running with real supervisors and Jupyter.
- These were isolated tests. They do not justify restarting active owners or promise that kernel variables survive Stop, Restart or natural server exit.
- Keep a fresh backup and specification for recovery. Preserve newer writes and conflicts; an offline fixture is not a backup of current user data.

Sources: [JUPYTER_APP_LIFECYCLE.md](JUPYTER_APP_LIFECYCLE.md), [JUPYTER_START_CONTROLS.md](JUPYTER_START_CONTROLS.md), [JUPYTER_AUTOSTART_BACKFILL.md](JUPYTER_AUTOSTART_BACKFILL.md)

## 30 Operator appendix: context and performance

A context budget is not a promise of latency or concurrent full-size requests.

- The documented budget is 393,216 tokens (384K; 1,048,576 until 13 November 2026) including instructions, tools, history, output and reserve. Confirm the selected deployment profile.
- Distinguish preparation latency, streaming rate and end-to-end completion. A small prompt can carry a large existing conversation.
- Use the speed comparison (not included in this public source projection) for current throughput. Measured speeds are not an SLA.

Sources: [DSH_USER_MANUAL.md](DSH_USER_MANUAL.md), [DSH_PLATFORM_GUIDE.md](DSH_PLATFORM_GUIDE.md)

## 31 Continue with the current manuals and course notes

Use the matching guide edition and retain dated evidence separately.

- Use the current guide, lifecycle manual and 56-second walkthrough for status labels, access approval and safe Jupyter handover.
- Use the authenticated app-sharing guide for selected users, protected ports, recipient revocation and application responsibilities.
- Read the accompanying course crosswalk with older code lessons. Archived media and experiments are dated references, not current runtime acceptance.

Sources: [JUPYTER_APP_LIFECYCLE.md](JUPYTER_APP_LIFECYCLE.md), [AUTHENTICATED_APP_SHARING.md](AUTHENTICATED_APP_SHARING.md), [COURSE_DELIVERY.md](COURSE_DELIVERY.md)




















## One library and one reading route



Start at the central library index. Use this guide for common tasks, the architecture page for placement and trust boundaries, the three-control page for enforcement responsibilities, and the OWASP matrix for the 80 stable feature IDs. Older topic pages remain reachable at their original URLs as supporting detail or dated evidence; their pointers identify the canonical explanation.

The complete category/A–Z source catalog remains available from the index in a collapsed catalog. Consolidation merges current guidance into these canonical routes; it does not delete old bodies, raw evidence, media, or history. Source availability, publication and operational acceptance remain different states.



## Two governing references and three control layers



The architecture PPTX (10 slides, SHA256 27cd3a8a0008da8186b1e8018872291cad164a6586045e8ff935a1385ca335db) and private four-sheet risk workbook (SHA256 214e604a349bf1955171504f4ba42e1f59fb01101fc717a4d9453ef6d860d937) are the governing editions. The workbook payload remains private.

Workbook anak_tool&risk_ai_draft J1/K1/L1 define policy/human, harness/deterministic and infrastructure/resource controls. M1 is audit across all three. CIA and leakage/damage/result-exposure are risk objectives, not alternative names for the three control layers. PPTX slide 2 separates runtime containment from independent resource authorization within the third layer.

The 80 feature IDs and ASI01–ASI10 taxonomy remain stable, including four cross-cutting ALL rows. Their current control-family assignments are documentary interpretations, not executed tests. Per-feature implementation, test-source references, executed receipts, deployment identity and live acceptance must remain separately recorded. A source/test filename is not tested evidence.

The architecture speaker notes also require server-bound user/project/identity fields: the model may propose a named tool/profile, but cannot select its authority. MCP, direct calls and custom RPC are alternative transports, not isolation mechanisms. Delegation must retain the same authorization gate. Protected audit records must bind owner/project/run, approved request, effective identity and result without agent-writable or secret-bearing logs.

Acceptance must observe termination of actual child processes and underlying database/Spark work after cancellation, not only a wrapper response. Hard deadlines and bounded output/retry/resource profiles are separate from a human cost decision. GPU assignment alone does not prove VRAM isolation; hardware/runtime support and effective limits require evidence.



| Control | Enforcement responsibility | Required acceptance evidence |

| --- | --- | --- |

| Policy / human (J1) | Choose purpose, owner, allowed profile and exceptions; approval cannot permit a forbidden operation. | Recorded owner decision and exact scope. |

| Harness / deterministic (K1) | Trusted dispatcher, typed inputs, bounded tools and task budget; test equivalent terminal/Jupyter routes. | Request/decision/result and exact source revision; observed allow and deny behavior. |

| Infrastructure / resource (L1) | OS identity, mounts, network and quota plus SQL/HDFS/service ACLs independent of agent intent. | Actual workload identity, effective authorization and cross-user/route denial. |

| Audit across layers (M1) | Protected attribution and original evidence; never promote a self-reported read-only flag. | Immutable original outputs, hashes, timestamps and runtime/source binding. |



## Identity, kinit, sessions, isolation and persistence



DSH Local or AD/LDAP sign-in identifies the browser owner; it does not create a Kerberos ticket. A Kerberos bootstrap is an explicitly authorized identity operation outside the agent-facing shell. Never pass passwords, tickets, keytabs or a principal's secret through prompts, logs or public examples.

Historical evidence names FILE:/state/kerberos/ccache and Livy/Spark sessions 631–632. No retained current kinit/klist transcript, ticket expiry/renewal check, cross-user cache isolation test or driver/executor identity proof is established by the library. These remain UNVERIFIED; the existence of a cache pathname is not successful authentication. Same-UID arbitrary Python or terminal code can read the same mounted credentials unless a separate OS/mount/resource boundary prevents it.

Before claiming Kerberos acceptance, the assigned operator must retain a redacted identity/expiry readback, cache owner/mode and actual mount scope, allowed source read and denied unauthorized access, renewal/expiry behavior, separate-session/cross-user denial, and Spark driver/executor plus HDFS authorization. Public evidence must omit credentials and customer data. This checklist is not a new execution request.

A browser session, conversation, agent task, Jupyter kernel and Livy/Spark session have different lifecycles. Persisted workspace/history files can survive an image or process replacement when the exact PVC/mount/profile is retained; kernel variables and running processes do not thereby survive. Fresh signup can remove the template supervisor sidecar and initialization containers, using a separate initialization Job. Container placement and shared-UID access must be verified against the actual profile, image and Pod.

C2's 16 November read-only observation records the managed workspace at zero replicas and no Pod; configured 393216 context and an image pin are not live context, compaction, isolation or persistence acceptance. OpenShell and A2A remain route/image-specific qualification work. Banking accounting and its genuine completion are separately owned.

Connector design: use dialect-aware complete-statement SQL validation, reject unsupported multiple statements and bind any approval to exact query/targets/profile. SQL AST checks and EXPLAIN are defense in depth; resource-side source SELECT grants and separately scoped scratch writes remain authoritative. Direct HDFS/Spark reads need their own ACL/plugin validation and may bypass SQL row/column/table policy. Delegated credentials may reach driver/executors and therefore submitted code; never claim all credentials stay outside arbitrary cluster code.

Filesystem and code design: session-fixed roots and safe directory-relative/symlink-resistant access must handle check/use races. Mount retained inputs/artifacts read-only to arbitrary code and use a trusted versioning/publish path for controlled updates; a gateway approval cannot protect a file from equivalent direct Python writes. Do not mount broad host paths, reusable connector keytabs/tokens or container-control sockets into generated-code runtimes.

Local Git design: fix repository/branch, sanitize configuration/environment, disable exposed hooks/pagers/external diff/filter/helper paths, and reject arbitrary config or identity/endpoint overrides. Agent-editable hooks cannot be the trusted scanner. Direct writable .git access can bypass a Git-tool policy, so retained history/audit needs an independent protected boundary. Remote push and destructive history operations require separately authorized workflows.

Retrieval and helpers: server-side project/tenant authorization fixes collection scope; ingestion is a separate approved maintenance process, with source IDs/versions, bounded results and independently preserved originals. Prompt labels do not prevent injection or grant permissions. Typed helper operations use fixed executables/argv without shell interpolation, bounded output and process-tree deadlines; credential bootstrap remains outside the agent-facing arbitrary shell. A dedicated filesystem gateway, persistent kernel, local retrieval, Spark and DevOps connector are design choices, not automatically selected or delivered capabilities.



| State or setting | What is established | What remains unverified |

| --- | --- | --- |

| Gateway | Fresh metadata/source hash observation; existing login owner routing. | Complete global quiet/session/task/watcher aggregate; do not infer zero from missing counters. |

| Managed workspace | Stopped template with configured context 393216; preserved PVC identities in dated evidence. | Current startup, effective per-agent context/compaction, application workflow and cross-user denial. |

| Kerberos / resource access | Historical cache/session references only. | Current kinit/klist, cache lifetime/permissions/isolation and effective SQL/HDFS/Spark identity. |

| Saved work | File/history persistence is a mount/format property distinct from a live process. | Current profile-bound restart/reopen evidence; do not restart active owners for documentation. |



## Internal and cloud profiles have different policies



Internal on-prem multiharness, including an Internet-enabled enterprise workspace, targets DeepSeek through the managed LiteLLM route only and fixed 393216-token context with the approved compaction/output limits. Internet access is not permission to select an external model provider. Defaults alone do not enforce this policy; user-writable settings, environment overrides, direct HTTPS/proxy relays and terminal/Jupyter paths require actual refusal or network-denial evidence.

multiharness.cloud and superharness.cloud are separately owned customizable cloud/arena roadmap profiles. Provider choice and credentials are explicit user decisions. A free-model default is an acceptance target, not established by a paid smoke test; there is no automatic paid or BOT-funded fallback. Model calls require verified payer, project and authentication authority. No cloud deployment or model call is requested by this documentation.

Publish truthful documentation before runtime restriction qualification. Subsequent live 393216/provider tests belong to the sole assigned operator with a bounded owner-approved workload; a stopped template, green pipeline or diagram cannot satisfy them.

The cloud startup candidate is disabled until an approved free route is configured: unconfigured startup refuses FREE_ROUTE_SETUP_REQUIRED before native runtime spawn. This is source behavior, not a functioning free-model service. Explicit customization requires matching provider configuration and explicit paid/unknown-cost consent, with no automatic fallback. Native compatibility and Linux initializer qualification remain separate. Cloud deployment is not yet qualified.



| Profile | Provider/context target | Network and acceptance distinction |

| --- | --- | --- |

| On-prem Internal | Managed DeepSeek/LiteLLM; fixed 393216 context. | Approved internal routes only; effective policy/compaction and alternate-route denials pending. |

| On-prem Internet-enabled | Same enterprise model restriction; Internet grant does not permit provider bypass. | Current broad HTTPS bypass is unqualified; NetworkPolicy selection and actual traffic must be verified. |

| Customizable cloud / arena | Explicit user provider configuration; verified free default target. | Separate credentials/billing/host ownership and task consent; no implicit paid fallback or enterprise entitlement. |



## Minimal-intervention arena and self-improvement roadmap



Roadmap, not live autonomous acceptance: the user states a bounded goal, permitted inputs/tools, budget and expected evidence once. A harness proposes an execution plan and runs only inside the approved authority. Routine reversible steps may proceed unattended inside that scope; exceptions pause for their exact owner.

Self-improvement means proposing and evaluating versioned source/configuration changes against frozen offline fixtures and retained real outcomes. Agents cannot approve their own permissions, loosen checks, alter billing, exfiltrate data, delete evidence or deploy their own candidate. A trusted release owner independently reviews the diff, evidence and rollback before activation.

Arena comparisons hold task inputs, resource budgets and scoring constant across DSH SDK, Claude Code and Deep Agents. Separate candidate source tests, reproducible artifacts, deployment, served content and live task acceptance. A successful HTTP wrapper or winning score alone is not operational acceptance.



| Stage | Automatic work inside scope | Owner decision / exit evidence |

| --- | --- | --- |

| 1 — Observe | Read allowed source and retained evidence; identify gaps without new provider calls. | Named task scope, provenance and unchanged originals. |

| 2 — Propose | Create an isolated candidate and run approved pure/offline fixtures. | Frozen comparison, no weakened checks, exact diff and failure history retained. |

| 3 — Review and qualify | Prepare a finite qualification request and rollback evidence. | Independent owner authorizes exact workload/payer/identity; real allow/deny/cancel/recovery results. |

| 4 — Release | Existing publisher verifies immutable content and route/source identity. | Release owner controls activation; verified receipt and affected live behavior. |

| 5 — Learn | Summarize outcomes and propose the next bounded improvement. | No self-expansion of authority or automatic restart/retry/deletion; new scope needs its owner. |


Public source edition: example.invalid URLs are deployment examples, not verified live services.
