# Governed Harness and managed agent-runtime comparison

## Purpose and decision boundary

This document compares the **DSH Governed Harness** with three execution runtimes that it can broker: **DSH Python SDK**, **Claude Code**, and **Deep Agents**. It also compares each runtime with a separately deployed counterpart outside the Governed Harness.

The enterprise scenario is deliberately strict:

- highly classified internal data;
- RKE2 Kubernetes in an isolated network segment without Internet access;
- one immutable internal model route through `litellm-gateway`;
- no user-selectable provider, endpoint, model, proxy, external fallback, or direct model credential;
- independently deployed counterparts use the same isolated RKE2 environment and the same immutable LiteLLM-only route, but are **not integrated with DSH AD/LDAP or its user/session broker**.

The comparison is about three controls:

1. **Prevent external leakage** — stop protected input, context, tools, files, credentials, and results from leaving approved boundaries.
2. **Prevent damage or excessive access** — limit what generated code and tools can read, change, execute, consume, or delegate.
3. **Keep results contained** — bind tasks, persisted state, results, sharing, recovery, and audit evidence to the correct authorized user and environment.

The Governed Harness is the enterprise **control plane and policy wrapper**. The other three are **execution runtimes**. They are not equivalent layers. A runtime may have useful native permissions, checkpoints, or tool controls, but it does not automatically inherit DSH identity, storage, network, audit, or lifecycle guarantees when deployed on its own.

## Reference architecture

```text
AD/LDAP or provisioned local identity
        |
        v
dsh-gateway: authentication, session, owner/environment assignment
        |
        v
/agent-tasks broker: runtime + project + backend + write-mode approval
        |
        +--> DSH Python SDK
        +--> Claude Code
        +--> Deep Agents
        |
        v
private per-user RKE2 workspace
        |
        v
guarded local model request identity and one-start ledger
        |
        v
litellm-gateway -> context-forwarder -> deepinfer-dspark
```

`OpenShell` is a proposed stronger task-isolation backend. It remains disabled until its live acceptance and rollback gates pass. It is not counted as a current control.

## Executive comparison

| Dimension | DSH Governed Harness | DSH Python SDK inside it | Claude Code inside it | Deep Agents inside it |
|---|---|---|---|---|
| Primary role | Enterprise control plane | Programmatic/checkpointed agent runtime | Coding-oriented CLI agent | Composable Python agent harness with tools, files and subagents |
| Identity authority | DSH AD/LDAP or provisioned local account, server-side session and environment assignment | Receives the task identity and project boundary from the broker | Receives broker-launched task context; native CLI identity is not accepted as DSH identity | Receives broker-launched task context; Python agent identity is not accepted as DSH identity |
| Model route | Immutable internal `litellm-gateway`; no external provider choice | Guarded local route only | Managed launcher and policy force local route; no native external sign-in permitted | Preconstructed managed model forces local route; proxy environment ignored |
| Workspace | Per-user/per-environment private mounted workspace and history | Broker-selected project below `/workspace` | Started in the approved project below `/workspace` | `FilesystemBackend` rooted below approved `/workspace` project |
| Tool/write control | Broker binds runtime, backend, project and write mode to explicit approval | Approval/resume semantics can interrupt sensitive steps | Native permissions are an additional layer; harness still enforces project/write scope | `interrupt_on` can pause write, edit and execute; harness still owns user/task authorization |
| Network boundary | RKE2 NetworkPolicy, internal DNS restrictions, No-Internet segment, no model fallback | Inherits Pod/network boundary | Inherits Pod/network boundary; managed launcher must suppress proxy/provider overrides | Inherits Pod/network boundary; managed HTTP clients do not trust ambient proxy variables |
| Result ownership | Owner/environment-bound task, history, files, app routes and broker output | Checkpoint/result must be bound to broker task and owner | Session/output must be captured by broker rather than treated as a free-standing CLI session | Checkpoint/files/results must be bound to broker task rather than only a LangGraph thread |
| Cancellation/recovery | Broker state, exact task identity, no replay after uncertain execution | Checkpointed interrupt/resume is the strongest native fit | Process cancellation is useful, but exact model-start identity and recovery need the wrapper | LangGraph checkpoint/HITL is useful, but worker and model-start identity still need the wrapper |
| Current acceptance | Deployed control surface; some successor controls remain under qualification | One bounded Test marker accepted with exact guard/server/spend-log join; native approval/resume remains incomplete | One bounded Test marker accepted with exact result plus guard/server/spend-log join; full delegated lifecycle remains incomplete | One bounded Test marker accepted, after Claude reconciliation, with exact result plus guard/server/spend-log join; full delegated lifecycle remains incomplete |

## Primary enterprise risk-control analysis

This is the controlling comparison. It starts from the requested operating model—highly classified internal data, an isolated RKE2 segment without Internet, one immutable local LiteLLM route, centrally provisioned runtimes, and no user-selectable model/provider/endpoint—and evaluates each control against the three required outcomes. OWASP is used later as a supporting threat taxonomy; it does not replace these enterprise decision columns.

| Enterprise requirement / control domain | Prevent external leakage | Prevent damage or excessive access | Keep results contained | Governed Harness enforcement | SDK / Claude Code / Deep Agents inside the harness | Same runtime deployed alone without DSH AD/LDAP | Current evidence and constraint |
|---|---|---|---|---|---|---|---|
| Human identity and session ownership | Prevents a tool or result route from accepting a prompt-supplied identity or an unrelated provider login | Stops a user or agent from borrowing another user's authority | Binds task, history, files, result stream and recovery to the authenticated owner and environment | `dsh-gateway` authenticates the account, resolves the assigned environment and supplies server-side owner context | All three consume the broker identity; none becomes an identity authority | Must add its own enterprise IdP, session service, owner mapping, revocation and collision handling | Gateway identity exists; full delegated identity acceptance remains incomplete |
| Immutable model/provider route | Blocks direct external providers, fallback endpoints and user-selected proxies | Prevents bypassing central model budgets and approved model behavior | Keeps model responses on the controlled internal route and under one audit correlation | Only `litellm-gateway` is admitted; network and launcher policy reject provider/endpoint overrides | SDK uses the guarded client; Claude uses managed launcher settings; Deep Agents receives a preconstructed managed model | Must independently lock endpoint/model/key source, suppress updates/telemetry and prove final-wire egress denial | One bounded marker per runtime is reconciled; arbitrary tools and every override route are not fully accepted |
| No-Internet network segment | Denies uncontrolled outbound transport even if generated code attempts a socket call | Limits remote command-and-control and dependency download during execution | Prevents result publication to an unapproved destination | RKE2 NetworkPolicy, restricted DNS and separate Internet preparation environment form the outer boundary | Inherit the Pod network boundary; native tool allowlists are only defense in depth | Needs equivalent namespace, NetworkPolicy, DNS, proxy and package-promotion controls for every standalone service | “No Internet” still permits explicitly approved internal services; it is not an air gap |
| Per-user, per-environment workspace | Prevents one environment or user from supplying another user's classified files to a task | Restricts file reads/writes to the assigned project and storage mounts | Keeps outputs, checkpoints and history within the correct owner/environment | Private mounts, owner-bound routes and explicit project selection below `/workspace` | SDK project, Claude working directory and Deep Agents filesystem backend are rooted in the broker-selected project | Must build independent tenant storage, path confinement, symlink defense, backup/retention and owner routing | Mount and route controls exist; every alternate tool/path still requires affected-behavior tests |
| Task intent, project and write-mode binding | Stops retrieved content from silently broadening what may be transmitted | Prevents goal hijack from turning a read task into code execution or writes | Keeps the result tied to the approved purpose rather than a substituted task | Broker persists runtime, backend, project, write mode, generation and operation identity | Native plans/checkpoints/subagents remain subordinate to that envelope | Must implement a durable intent envelope, material-change detection and re-approval | Scope binding exists; semantic intent-diffing and goal-hijack red-team acceptance remain pending |
| Tool admission and exact action approval | Blocks tools that could export files, credentials or result data | Limits tool set, arguments, target, duration and side effect; preview is not execution | Records which exact approved action produced the retained result | Server-side policy plus one-use approval and task ledger; browser fields are not authority | SDK interrupt, Claude permissions and Deep Agents `interrupt_on` add runtime-specific checks | Each standalone service needs its own policy-enforcement point, approval UI/API and replay protection | Source and bounded marker evidence exists; broad tool/action acceptance is incomplete |
| OS/container execution boundary | Restricts shell/process network and filesystem reach even after prompt injection | Non-root execution, dropped capabilities, no host socket/path and quotas limit blast radius | Prevents an execution worker from reading another user's result store | RKE2 Pod security, mounts, quotas and service-account suppression are authoritative | Runtime sandboxes and permission rules add narrower controls but cannot replace the Pod boundary | Must reproduce hardened Pod specifications and prove the absence of ambient cluster/host authority | OpenShell is not credited: its current live ledger is 0/25 |
| Credential custody and connector use | Secrets are not put in prompts, model context, child process output or external endpoints | Exact connector operation, scope and expiry limit what a compromised task can do | Connector results and audit metadata remain owner/environment-bound | Alias-based broker, encrypted storage and policy checks; secret values are not returned to the harness | Runtimes request an alias-bound operation rather than receiving the stored credential | Needs a separate vault/broker, per-owner policy, approval, redaction, revocation and audit | Only configured connector types are covered; OAuth/Kerberos remain separate qualification areas |
| Package, plugin and agent supply chain | Prevents malicious dependencies/plugins from adding covert egress | Prevents unsigned tools, prompts or images from expanding capabilities | Preserves which code/policy generated a result | Pinned source, packages, images, managed settings and reviewed promotion/rollback | SDK tools, Claude hooks/plugins/MCP and Deep Agents middleware/subagents must be operator-owned and immutable | Must maintain SBOM/AIBOM, curated registry, signed artifacts, drift checks and staged rollback independently | Public CI and selected hashes exist; complete private image provenance remains a release gate |
| Context, memory and checkpoint admission | Prevents cross-user/context reuse and secret persistence in an unintended store | Stops poisoned memory from changing later goals or approvals | Namespaces, versions and binds persisted state to the right owner/task/environment | Private history plus broker task identity; sensitive memory needs authenticated write admission and rollback | SDK checkpoints, Claude session memory and Deep Agents stores are untrusted until admitted | Must build tenant namespaces, provenance, expiry, anomaly checks, quarantine and rollback | Storage separation exists; poisoning/trust-score acceptance is incomplete |
| Inter-agent/subagent handoff | Prevents one stage from sending classified context to an unapproved recipient/runtime | Preserves capability limits and blocks replacement/stale identities | Binds every stage result to the parent owner, task, generation and audience | Typed stage contract, durable correlation and anti-replay state are required | SDK handoff, Claude subagents and Deep Agents subagents must inherit the same outer identity and budgets | Needs mutually authenticated transport, typed/versioned contracts, nonce/timestamp and delegated-scope monitoring | Authenticated cross-runtime delegation is not live-accepted |
| Model-start, recursion and resource budgets | Prevents repeated calls from multiplying exposure | Limits cost, GPU/CPU/RAM/storage use, recursion and cascading actions | Ensures the retained result corresponds to the admitted call rather than a hidden retry | One-start ledger, task/stage timeout, quotas and no automatic retry after ambiguity | Runtime turn/recursion limits add defense in depth; outer ledger remains authoritative | Must implement durable budgets and join them to infrastructure and provider receipts | Five authorized marker starts are consumed; no additional real starts are implied |
| Cancellation and descendant fencing | Stops an abandoned task from later transmitting data | Stops the exact process tree, subagents and admitted worker rather than only changing UI state | Prevents a cancelled task from publishing a late result or being silently replayed | Exact task/worker identity, revoke, process/worker stop, absence proof and terminal ledger state | SDK execution, Claude process tree and Deep Agents graph descendants require runtime-specific stop adapters | Each service needs exact-worker cancellation, absence verification and uncertain-outcome reconciliation | OpenShell worker source is prepared, but no successor image or live cancellation gate has passed |
| Recovery, restart and no-replay | Prevents automatic resend of classified prompts after uncertain transport | Avoids duplicate writes/model calls and rejects stale checkpoints/replacement identities | Restores only the correct owner's state and labels uncertain outcomes honestly | Durable task state, known-working rollback and guard/server/spend reconciliation | Native resume is allowed only through broker-bound identity and approval | Must implement its own durable operation ledger and reconcile every ambiguous execution | Bounded marker non-duplication is proven; full lifecycle/recovery acceptance is incomplete |
| Result streaming, storage and sharing | Filters result delivery through authenticated same-origin routes | Prevents generated output from automatically creating a public service or side effect | Private result storage plus explicit application audience keeps disclosure intentional | Owner-bound event stream/history; app sharing is a separate approved control plane | Runtimes have no independent authority to publish or change the audience | Must provide authenticated result API, tenant storage, redaction, retention and sharing authorization | Terminal/model output may contain classified data; metadata audit must avoid storing secret bodies |
| Audit and source-to-runtime provenance | Detects attempted leakage and reconstructs who/what sent a request | Supports rollback, incident response and accountability for changes/actions | Proves which owner, code, model route and result belong together | Correlates owner, environment, task, runtime, project, operation, image/source and model-call identity | Each runtime must emit bounded events into that correlation rather than maintain an unowned private log | Requires a separate enterprise audit design and immutable source/artifact/runtime mapping per service | Passing CI/readiness is not runtime acceptance; private build and current image mapping remain incomplete |

### Risk-centered conclusion

- **External leakage:** the decisive controls are the isolated network, immutable local model route, private mounts, credential broker and authenticated result routes. Runtime-native tool controls reduce attack surface but cannot prove containment by themselves.
- **Damage or excessive access:** the decisive controls are server-bound task intent, project/write mode, exact-action approval, hardened Pods, budgets, one-start/no-replay state and exact descendant cancellation. A fluent plan or native permission prompt is not authorization.
- **Result containment:** the decisive controls are owner/environment identity, tenant storage, authenticated streaming, explicit sharing audiences, checkpoint ownership, recovery fencing and end-to-end provenance. A common model endpoint does not establish result ownership.
- **Standalone counterparts:** placing the same runtime in the same RKE2 cluster and forcing the same LiteLLM endpoint only reproduces part of leakage control. Without DSH AD/LDAP integration and its broker, every standalone service must independently rebuild identity, task authorization, tenant storage, approval, audit, recovery and sharing controls.

## OWASP Agentic Top 10 crosswalk

The OWASP Top 10 for Agentic Applications 2026 adds a useful threat taxonomy to the three enterprise outcomes above. It does not certify this deployment and it does not turn a documented control into a verified runtime control. The table below maps each OWASP risk to the relevant Governed Harness and runtime responsibilities, then states the present evidence boundary.

| OWASP risk | Relationship to the three enterprise risks | Governed Harness responsibility | Runtime-specific responsibility | Standalone counterpart requirement | Current evidence boundary |
|---|---|---|---|---|---|
| ASI01 Agent Goal Hijack | Leakage and damage when untrusted content changes the active objective or tool plan | Keep server-derived task scope, approved project/write mode and one durable operation identity; stop or re-approve material goal changes | SDK/Claude/Deep Agents must treat retrieved text, files, tool output and peer messages as data rather than higher-priority authority | Implement an equivalent signed or durable intent envelope, goal-change policy and audit trail | Task scope and bounded marker correlation exist; semantic intent-diffing and adversarial goal-hijack acceptance are not yet established |
| ASI02 Tool Misuse and Exploitation | Damage, excessive access, leakage and cost from legitimate tools used with unsafe arguments or sequences | Authenticate each task/action, constrain tool set, project, write mode, egress, duration and model-start budget; fail closed on ambiguity | SDK approval, Claude permissions and Deep Agents `interrupt_on` add runtime-specific checks but do not replace outer authorization | Build a policy-enforcement point, per-tool scopes, dry-run/approval, rate/cost ceilings and immutable tool audit | Source and bounded marker checks exist; arbitrary tool/action acceptance is incomplete |
| ASI03 Identity and Privilege Abuse | All three risks through confused-deputy behavior, transitive delegation or stale privilege | Bind owner, environment, purpose, project, generation, operation, audience and expiry server-side; reject prompt/body identity | Every child, resume and tool action must inherit the exact bound task identity without gaining ambient credentials | Provide human authentication plus per-agent/task identity, time-bounded credentials, action authorization, revocation and delegated-scope monitoring | Gateway identity exists; full delegated privilege and approval lifecycle acceptance remains incomplete |
| ASI04 Agentic Supply Chain Vulnerabilities | Leakage and damage from compromised models, tools, prompts, packages, plugins or agent descriptors | Admit pinned source, packages, images, manifests and policies; preserve source-to-image-to-runtime receipts and rollback | Pin SDK/CLI/library versions, disable self-update/user-loaded extensions and verify installed bytes | Maintain SBOM/AIBOM, signed artifacts, curated registry, staged rollout, drift checks and kill switch | Public CI and selected hashes exist; complete immutable successor-image and private release provenance remain open |
| ASI05 Unexpected Code Execution | Direct damage/leakage when generated or retrieved content reaches shell, interpreter or unsafe evaluator | Non-root restricted workload, bounded filesystem/network, explicit execute approval and no automatic cluster credential | Claude Bash, SDK tools and Deep Agents execution backends require separate allowlists/sandboxing and output validation | Separate generation from execution; provide sandbox, static/runtime checks, dedicated workspace and elevated-run approval | Container/source controls exist; OpenShell execution isolation is 0/25 and arbitrary-code acceptance is incomplete |
| ASI06 Memory and Context Poisoning | Leakage, result corruption and later damage through persistent or cross-tenant poisoned state | Owner/environment segmentation, trusted source labels, retention policy, versioned state and rollback/quarantine | Checkpoints, CLI memory and graph stores must not re-ingest outputs as trusted memory or cross owner/task boundaries | Add authenticated memory writes, provenance/trust score, anomaly checks, tenant namespaces, expiry and rollback | Per-user workspace/history exists; memory-write validation, trust weighting and poisoning red-team evidence are not fully established |
| ASI07 Insecure Inter-Agent Communication | Leakage, privilege abuse and result substitution across handoffs | Bind every stage/message to task, owner, generation, runtime, audience, correlation and anti-replay state; validate typed contracts | Claude subagents, SDK handoffs and Deep Agents subagents must preserve those bindings and capability limits | Add mutually authenticated transport, signed/versioned messages, nonce/timestamp replay defense and trusted discovery | Bounded single-runtime markers exist; authenticated cross-runtime delegation and replay-resistant handoff are not live-accepted |
| ASI08 Cascading Failures | Damage and availability loss when one bad result/action propagates across agents or systems | One-start ledger, quotas, stage caps, circuit breaker, external policy checks, exact cancellation and no automatic retry after ambiguity | Each runtime must stop descendants and downstream propagation on failed/uncertain gates | Add independent policy engine, rate limits, blast-radius caps, lineage, replay testing and downstream human checkpoints | No-duplicate bounded markers are proven; multi-stage cascade containment and recovery remain incomplete |
| ASI09 Human-Agent Trust Exploitation | Damage or result exposure when persuasive output causes unsafe approval | Show source-derived task scope, requested side effects and exact approval target; separate preview from effect and retain immutable audit | Native rationales are untrusted; runtime UI must not convert confidence or fluent text into authority | Provide plain-language risk summary, provenance, preview/diff, high-impact confirmation, suspicious-interaction reporting and operator training | Exact approval UX and risk-display acceptance are incomplete; current controls must not claim model explanation is proof |
| ASI10 Rogue Agents | All three risks through behavioral drift, concealment, collusion or unauthorized persistence | Enforce declared capabilities, anomaly limits, cancellation, credential revocation, quarantine, clean restoration and re-attestation | Runtime/subagent behavior must stay inside the bound tool/model/project manifest; no self-expansion | Add behavioral baseline, signed capability manifest, watchdog/kill switch, forensic quarantine and approved reintegration | Broker limits exist; behavioral attestation, rogue-agent detection and full kill/reintegration qualification are not established |

The crosswalk shows why fixed local LiteLLM and an isolated RKE2 network are necessary but insufficient. They mainly reduce external model/network exposure. OWASP ASI01, ASI03, ASI06, ASI07, ASI09 and ASI10 additionally require intent, identity, memory, message, human-trust and behavioral controls that must be implemented and tested above the model route.

## Detailed integrated feature matrix

Legend: **Enforced** means a directly implemented control at the stated layer. **Inherited** means the runtime benefits from the Governed Harness/RKE2 boundary but does not provide it itself. **Native** means the upstream runtime has a relevant mechanism that still requires enterprise configuration. **Pending** means source or partial tests exist but live acceptance is incomplete.

| Detailed feature / enterprise requirement | Risk controlled | Governed Harness control | DSH Python SDK inside harness | Claude Code inside harness | Deep Agents inside harness | Current limitation or acceptance boundary |
|---|---|---|---|---|---|---|
| AD/LDAP sign-in | Leakage, excessive access, result exposure | Enforced at `dsh-gateway`; account conflicts fail closed; local recovery identity remains separate | Inherited; SDK never becomes the identity authority | Inherited; Claude account/login is not used as enterprise identity | Inherited; Python/LangGraph identity is not used as enterprise identity | Runtime launchers must never accept a claimed username from prompt/body as authority |
| Server-side user-to-environment assignment | All three | Gateway resolves owner, No-Internet/Internet environment and assigned runtime | Receives resolved assignment | Receives resolved assignment | Receives resolved assignment | Must remain server-derived; forged owner/environment fields are rejected |
| No-Internet default | Leakage | Main protected workspace is placed in restricted segment; Internet preparation is separate | Inherited network boundary | Inherited network boundary | Inherited network boundary | “No Internet” still permits approved internal services; it is restricted egress, not an air gap |
| Immutable local model endpoint | Leakage, excessive use | Only canonical LiteLLM route is offered; browser cannot select a host | Guard endpoint and model fixed by broker/policy | Managed launcher fixes `ANTHROPIC_BASE_URL`/equivalent route and rejects model/endpoint overrides | Preconstructed `DSHManagedChat` fixes model, base URL and key source | Configuration must also deny environment, CLI, plugin, MCP and code-level bypasses |
| No external provider fallback | Leakage | LiteLLM route and network policy disallow external model fallback | No alternative endpoint accepted | Native Claude provider sign-in/update/telemetry paths must be disabled or unreachable | Provider/model overrides and ambient proxy variables are rejected | A fixed UI model selector alone is insufficient; final-wire network evidence is required |
| Model credential isolation | Leakage, result exposure | Worker receives only a restricted client route/credential, not provider admin credentials | Guarded request uses task-scoped identity | API-key helper/managed token must not expose value to task, output or shell | Managed model constructs client without user-supplied key/endpoint | Credential presence is not proof of safe use; logs and subprocess environment must be reviewed |
| Final-wire request guard | Leakage, duplicate cost, audit | Correlates durable task operation with one admitted model start | Accepted once in Test with exact operation/call-ID/spend-log join | Accepted once in bounded Test with an exact marker and matching guard, server and spend-log call ID | Accepted once in bounded Test, only after Claude reconciled, with the same exact identity join | These prove one guarded marker per runtime, not approval/resume, cancellation/recovery, arbitrary tools or Production qualification |
| Prompt/context budget | Excessive use, availability | `context-forwarder` validates backend-reported `max_model_len`; long requests receive bounded admission | Uses managed context limit | Native context may grow; wrapper applies shared limit and route | Deep Agents summarization/offload is useful, but wrapper enforces final counted budget | Summarization reduces context size, not data sensitivity or tool authority |
| Per-user workspace | Damage, result exposure | Separate persistent workspace/history per user and environment | Project must resolve below `/workspace` | Working directory is set below approved `/workspace` project | `FilesystemBackend(root_dir=approved_project, virtual_mode=True)` | Persistent storage is not independent backup; process memory is not persistent |
| Cross-user file denial | Result exposure | Different mounts and owner-bound routes; runtime has no peer-selection control | Inherited | Inherited | Inherited | Must test forged paths, symlinks, shared volumes and alternate tool routes |
| Cross-environment separation | Leakage, result exposure | No-Internet and Internet workspaces, history, attachments and credential state are separate | Inherited | Inherited | Inherited | Moving approved packages is a distinct reviewed artifact flow, not shared writable storage |
| Filesystem read boundary | Leakage | Mount and route boundary; task project is explicit | SDK tools limited by broker/project wrapper | Native working-directory prompts/sandbox add defense in depth | Backend path root and virtual filesystem constrain tools | Native permission prompts are not OS isolation; shell commands can exceed file-tool boundaries unless sandboxed |
| File write/edit approval | Damage | User approves write mode for the task; broker persists that decision | Checkpoint/approval can pause sensitive action | Native Edit/Write/Bash permission rules add a second prompt/policy layer | `interrupt_on` pauses `write_file`, `edit_file` and `execute` | Approval must be bound to exact task, arguments, generation and result—not a blanket session grant |
| Command execution | Damage | Non-root Pod, dropped privileges/capabilities, no host path/socket, resource limits | Only approved tools/commands in assigned worker | Claude Bash permissions and sandbox can further limit execution | `execute` exists only with a suitable backend and can be interrupted | Neither prompts nor tool allowlists replace kernel/container isolation |
| Kubernetes API access | Damage | User runtime has no automatic service-account token/default kubeconfig | Inherited | Inherited | Inherited | Presence of the `kubectl` binary grants nothing by itself; mounted credentials would change the risk |
| Network tools and fetch | Leakage | NetworkPolicy and internal DNS are the authoritative boundary | Inherited | Native WebFetch/MCP rules can reduce tool surface but are secondary | Tool list/backends can omit browser/fetch tools | Denying a named tool does not block arbitrary socket use from an allowed shell/process |
| Plugin/MCP/tool extension | All three | Only reviewed installed components should be available in immutable image | SDK tool registry must be operator-owned | Claude plugins, hooks, MCP and settings are powerful and must be managed/immutable | Deep Agents tools, middleware and profiles are Python code and must be operator-owned | User-loadable extensions are incompatible with “unchangeable” policy unless separately signed and admitted |
| Goal and intent binding | Leakage, damage | Persist declared task, project, write mode and generation; require a new decision for material scope change | Bind checkpoint/resume to the same approved intent | Compare planned tools/actions with the broker-approved task, not only the current prompt | Bind graph/subagent objectives and state to the same parent intent | ASI01-aligned semantic intent-diffing and goal-hijack red-team acceptance remain pending |
| Action-level authorization and ephemeral authority | Damage, leakage | Each sensitive operation is authorized against owner, task, exact arguments, purpose and expiry | Native approval response must be broker-bound and one-use | Native permission decision is defense in depth; wrapper decision remains authoritative | HITL decision must be exact-task and one-use | Long-lived ambient credentials or session-wide approvals would violate ASI02/ASI03 least-agency guidance |
| Component and prompt provenance | Supply chain, all three | Pin source, prompt/policy, package and image identities; retain promotion and rollback receipts | Pin SDK and registered tools | Pin CLI, plugins, hooks, MCP definitions and managed settings | Pin agent library, middleware, tools, backends and subagent definitions | Complete SBOM/AIBOM and clean source-to-binary reproducibility remain open |
| Memory write admission and provenance | Leakage, result exposure, damage | Separate owner/environment history; classify trusted sources; version, expire, quarantine and roll back sensitive memory | Validate checkpoint writes and prevent foreign resume | Treat CLI project memory and generated summaries as untrusted until admitted | Validate checkpointer/store writes and prevent automatic trusted re-ingestion | ASI06 trust scoring, anomaly detection and poisoning acceptance are not fully implemented |
| Inter-agent message integrity and anti-replay | Leakage, damage, result exposure | Typed stage contract with owner/task/generation/runtime/audience/correlation; refuse stale/replacement identity | Handoff must preserve exact operation and approval state | Subagent/session messages must be captured by the broker contract | Child graph messages/results must be schema-bound to the parent task | Cryptographic signing/mTLS is not claimed; live authenticated delegation remains pending |
| Cascade circuit breaker | Damage, availability | Stage/model-start limits, resource quotas, timeout, cancellation and no automatic retry after ambiguity | Stop continuation after failed/uncertain approval or tool result | Stop process tree and reconcile admitted request before replacement | Stop child graphs/workers and downstream propagation | Multi-agent cascade and restart non-replay acceptance remain pending |
| Preview separated from effect | Damage, human trust | Present exact planned side effect/diff before approval; preview cannot perform state/network changes | Approval payload must show exact operation | Plan/permission output is informational until exact effect is authorized | HITL preview/edit/reject must be distinct from execution | Current UI must not treat model rationale as an approval or safety attestation |
| Rogue-agent containment and reintegration | All three | Revoke task authority, stop exact worker/descendants, quarantine outputs/state, verify absence, then require fresh admission | Fence checkpoint and refuse stale resume | Kill exact CLI process tree and discard untrusted session continuation | Cancel graph/subagents and quarantine checkpoint/store state | Behavioral attestation, watchdog detection and clean reintegration are not yet qualified |
| Subagents/delegation | Damage, leakage, duplicate calls | Broker controls optional bounded handoff and one-start ledger | Delegation must retain task/owner/correlation | Claude subagents require managed permission/tool policy | Native subagents are a core capability with isolated context windows | Context isolation does not imply identity, network or cost isolation; each child needs inherited bounds |
| Human-in-the-loop | Damage | Task approval plus exact resume endpoint and durable broker state | Native checkpoint/interrupt is well suited | Native permission prompts are useful for CLI actions | Native LangGraph interrupts can approve/edit/reject/respond | Current native approval/resume integration is not fully accepted across all runtimes |
| Cancellation | Damage, cost | Broker cancellation targets the exact admitted worker/task | Must stop exact checkpointed execution | Must terminate exact CLI process tree and reconcile any admitted request | Must cancel exact graph/worker and descendants | “Cancel requested” is not enough; verify worker absence and no later result/model start |
| Uncertain execution / replay | Damage, duplicate cost | Uncertain operation is observed and reconciled; replacement identity is refused | Durable operation ID supports reconciliation | CLI exit alone cannot prove whether provider accepted request | Graph exception alone cannot prove whether provider accepted request | No automatic retry after ambiguous execution; join guard and server/spend evidence first |
| Checkpoint/resume | Availability, damage | Broker stores task state and controls resume authorization | Native strength; accepted marker does not yet prove full approval/resume | Native session resume exists, but must be bound to DSH owner/task | LangGraph checkpointer supports durable state and HITL | Resume identifiers must not allow another user/environment to acquire state |
| Output streaming | Result exposure | Same-origin authenticated task events and owner-bound task ID | Output captured through broker | CLI stream must be relayed, filtered and persisted by broker | Graph events/results must be relayed through broker | Terminal output may contain secrets or classified data; audit and user display need separate redaction rules |
| Result storage | Result exposure | Private history/workspace; explicit app sharing is separate | Saves only to approved project/history | CLI session artifacts must remain in approved project/history | Backend/checkpointer must use approved private storage | A runtime’s default local cache may not meet retention, ownership or backup rules |
| Application sharing | Result exposure | Explicit owner-selected audience; terminals/Jupyter remain owner-only | No independent sharing authority | No independent sharing authority | No independent sharing authority | Runtime output must not create a public route automatically |
| Audit correlation | All three | Task ID, owner, environment, runtime, project, backend, write mode, state and guarded model-call ID | One exact Test marker has complete join | Exact end-to-end join pending | Exact end-to-end join pending | Access logs are not full command/model/file audit; collect bounded metadata without secret bodies |
| Secret handling | Leakage | Alias-based credential broker; owner/workspace/environment/action checks; audit excludes secret values | Tool receives approved operation, not secret value where supported | Native credential storage is not used as enterprise custody | Model constructor and tool code must not accept arbitrary user secrets | OAuth/Kerberos and every connector remain separately qualified; DSH login is not a datalake ticket |
| Resource quotas | Damage/availability | RKE2 CPU/memory/storage/GPU admission, task duration and model concurrency controls | Inherited | Inherited | Inherited; subagents require explicit aggregate budget | Runtime-level `max_turns` or recursion limits are useful but not infrastructure quotas |
| Image/version pinning | Supply chain, leakage | Immutable reviewed image digest and source/hash readback | SDK version and adapter pinned | CLI version, launcher and settings pinned; auto-update disabled | Deep Agents/LangChain versions and dependency graph pinned | Source tests do not prove the built/running image; read back the actual digest and installed bytes |
| Recovery/rollback | Availability, result exposure | Known-working ConfigMaps/images/routes retained; guarded rollout and owner-state checks | Restore broker/checkpoint without replay | Restore launcher/image without restoring unsafe user settings | Restore model adapter/backend/checkpointer consistently | Rollback must include task ledger and storage state, not only Deployment readiness |
| OpenShell stronger isolation | Leakage, damage | Designed as optional per-task backend with namespace/node/budget/expiry controls | Not currently available | Not currently available | Not currently available | `0/25` live gates at the controlling checkpoint; no current security credit |

## Runtime-by-runtime usage examples inside the Governed Harness

### DSH Python SDK

**Best fit:** structured workflows requiring durable state, explicit interrupts, deterministic tool registration, and application-controlled resume.

**Example:** An analyst asks for a classified portfolio-quality review. The broker binds the request to the analyst’s No-Internet workspace and a read-only approved dataset tool. The SDK produces an intermediate exception list, pauses before writing the final workbook, and resumes only after the owner approves the exact action. The result stays in the owner’s project and the model call joins the same durable operation ID.

**Strength:** best architectural fit for checkpointed enterprise workflows.

**Current constraint:** one bounded marker call has been reconciled end to end; full native approval/resume, cancellation, recovery and business-workflow acceptance are still pending.

### Claude Code

**Best fit:** repository analysis, code changes, tests, debugging, and command-line workflows where native file/Bash permission controls provide useful defense in depth.

**Example:** A developer requests a change to an internal service. DSH selects the approved repository project, starts Claude Code non-interactively with no provider/model override, permits reads and tests, and requires both DSH write approval and Claude’s managed permission policy before edits. Network policy prevents public package/model access; the only model path is internal LiteLLM.

**Strength:** mature coding workflow and granular native tool permissions.

**Current constraint:** the earlier guarded attempt exposed unsupported safeguards metadata and failed with zero tokens. The corrected adapter now has one bounded Test marker with exact guard/server/spend-log identity reconciliation. That does not qualify managed tool/write approval, delegated work, cancellation/recovery, immutable-image provenance or Production behavior. Native permission prompts do not replace DSH owner, network, mount, or audit controls.

### Deep Agents

**Best fit:** multi-step research or analysis requiring planning, filesystem context, specialized subagents, middleware, and programmatic human approval.

**Example:** A risk team asks for a multi-section internal assessment. The main agent reads only the approved project, delegates independent sections to bounded subagents, and pauses on write/execute operations. All agents use the preconstructed local model and the same task ledger. Final artifacts are written only to the owner’s output directory.

**Strength:** most composable runtime for custom tools, subagents, backends and checkpoint logic.

**Current constraint:** composability is also its primary risk. Tools, middleware, profiles, backends and provider construction must be immutable operator code. One bounded guarded marker has now been accepted in Test after Claude reconciled, but this does not qualify arbitrary tools, subagents, approval/resume, cancellation/recovery or Production behavior.

## Individually deployed counterparts outside the Governed Harness

The following comparison assumes each counterpart is still pinned in RKE2, has no Internet route, and can reach only the same immutable local LiteLLM model. The difference is the absence of DSH AD/LDAP, owner/session routing, `/agent-tasks`, per-user DSH history, DSH app-sharing controls, and the central DSH task ledger.

| Detailed requirement | Standalone DSH Python SDK service | Standalone Claude Code Pod/service | Standalone Deep Agents service | Enterprise implication outside Governed Harness |
|---|---|---|---|---|
| User authentication | Must add a separate application/API identity layer | CLI identity is normally OS/process or Claude account; with external sign-in disabled, a separate front door is required | Must add API/web identity middleware | No AD/LDAP means Kubernetes/OS identity alone cannot identify the human requester |
| Human-to-task ownership | Application must create and persist its own owner/task mapping | Process/session owner must be mapped by a launcher service | Thread/checkpoint owner must be mapped by the application | Without this, task IDs, CLI sessions and graph threads can become bearer identifiers |
| Model lock | Can hard-code one LiteLLM client | Managed settings/environment/wrapper can pin endpoint and model; disable flags/settings that override them | Pass a preconstructed model and reject provider/model kwargs | Feasible for all three, but must be enforced in code/image/network, not documented as a convention |
| Network isolation | RKE2 NetworkPolicy and restricted DNS | Same | Same | Equal network containment is possible if policies are identical and independently verified |
| Workspace isolation | Must allocate a unique PVC/path and validate every request | One Pod/PVC per user or a trusted launcher must enforce working directory | Backend root/checkpointer/store must be unique per user | A shared service/PVC needs a new authorization layer equivalent to part of DSH |
| Write/tool approval | Build API/UI and durable interrupt/resume state | Native Claude permissions can prompt a terminal user; service mode needs a permission bridge | Native HITL supports interrupts but needs authenticated decision API | Runtime-native approval does not identify who approved unless the outer service does |
| Shell containment | Container security and tool wrapper required | Native sandbox is valuable defense in depth | Sandbox/LocalShell backend must be selected and configured | Same RKE2 hardening can be reproduced, but each service becomes separately governed |
| Subagent control | Custom | Claude subagents/settings require policy | Native capability; enforce child count/tools/budget | Parent identity and resource limits must propagate to every child |
| Cancellation | Must map cancellation to exact run/worker | Must terminate exact process tree and reconcile model request | Must cancel exact graph/workers and reconcile model request | A generic Pod delete is insufficient if the request may already have reached LiteLLM |
| Replay prevention | Implement durable operation and one-start ledger | Implement wrapper ledger around CLI | Implement wrapper ledger around graph invocation | This recreates a central feature of the Governed Harness three times |
| Result storage | Build private result service/PVC policy | Control CLI caches/transcripts/output directories | Control checkpointer/store/filesystem backend | No DSH history or sharing policy exists automatically |
| Result sharing | Build separate authorization and publication workflow | Same | Same | Do not expose a shared dashboard or object store without per-result ACLs |
| Audit correlation | Instrument API, tools, LiteLLM call ID and storage events | Add process/tool/model correlation around CLI | Add graph/tool/model correlation | LiteLLM logs alone identify model traffic, not the responsible human, files, or tool impact |
| Secrets | Provide a separate broker or workload identity | Disable native personal credential use; inject only restricted service route | Do not pass arbitrary credentials through model/tool state | Kubernetes Secret mounts alone do not give per-user/action authorization |
| Lifecycle/versioning | Pin SDK/service image | Pin Claude Code and disable auto-update | Pin Deep Agents/LangChain and dependencies | Three independent release/rollback tracks increase review and drift cost |
| Operational complexity | Medium | Medium–high because CLI is adapted into a service | High because the application owns tools, middleware, checkpoint and API | Rebuilding equivalent controls independently usually costs more than using the central wrapper |
| Best standalone use | A single-purpose internal workflow with its own strong application identity | A dedicated development appliance with one accountable operator per Pod | A specialized internal agent service with a fully governed API | Appropriate only when the service has a clear owner and explicitly replaces every missing DSH control |

## Risk-by-risk conclusion

### Risk 1 — external leakage

The immutable local LiteLLM route and RKE2 No-Internet segment are the strongest common controls. They can be made equivalent for integrated and standalone deployments. The Governed Harness adds consistent identity-to-environment routing, separate Internet preparation, approved package flow, credential aliases, final-wire model correlation, and one place to verify that all runtimes actually use the same route.

**Residual risk:** shell tools, plugins, MCP servers, internal services, mounted files, DNS, logs, and copied outputs can leak data even when model egress is locked. Test the actual running workload and final network path.

### Risk 2 — damage or excessive access

RKE2 security context, mounts, NetworkPolicy, service-account suppression and resource limits are the authoritative boundary. Claude Code permissions and sandboxing, SDK interrupts, and Deep Agents HITL/backends add useful runtime-specific controls. The Governed Harness makes these controls subordinate to a single approved user, project, backend, write mode and task ledger.

**Residual risk:** an approved shell or powerful tool can act with every permission of its Pod. Prompts and permission dialogs are not a substitute for least-privilege OS, storage and remote-service entitlements.

### Risk 3 — result exposure

This is where standalone deployments differ most. A locked model and isolated network do not establish who owns a task, checkpoint, CLI session, output file, result stream, or recovery action. The Governed Harness supplies owner-bound sessions, private histories/workspaces, explicit application audiences, task-state routing, and one audit correlation point.

**Residual risk:** authorized users can still view and copy results. Preventing further copying requires a separate information-handling and endpoint-control policy.

## Recommended enterprise operating model

1. Keep the Governed Harness as the only human-facing control plane.
2. Treat DSH Python SDK, Claude Code and Deep Agents as interchangeable **runtime choices**, never as identity authorities.
3. Lock the model at four layers: UI/catalog, runtime launcher/model object, final-wire guard, and RKE2 network policy.
4. Give each task one server-derived owner, environment, project, backend, write decision, operation ID and model-start budget.
5. Permit no user-loaded provider, endpoint, proxy, plugin, hook, MCP server, middleware or tool package in the classified profile.
6. Preserve separate runtime-specific policies: SDK checkpoint rules, Claude managed permissions/sandbox, and Deep Agents backend/HITL/subagent limits.
7. Require exact cancellation and recovery evidence; never resubmit an ambiguous model operation under a replacement identity.
8. Keep standalone counterparts only for narrowly owned services that independently implement every missing identity, storage, approval, audit and lifecycle control.
9. Do not credit OpenShell until its live product gates and rollback pass.
10. Re-evaluate the matrix whenever the running image, runtime version, broker source, LiteLLM adapter, tool set, storage mapping or network policy changes.

## Current verified status and limits

| Component | Verified current status | Not yet established |
|---|---|---|
| Governed Harness control surface | Deployed authenticated gateway and `/agent-tasks` capability surface; private workspace is enabled backend; local LiteLLM route is canonical | Complete live acceptance of successor handoff and every runtime path |
| DSH Python SDK | One bounded Test marker with exact task operation, guard reservation/finish, server call ID and spend-log join | Native approval/resume, cancellation, recovery and full classified workflow |
| Claude Code | Installed/selectable; one bounded guarded Test marker completed with an exact result and matching guard/server/spend-log identity | Full authenticated delegation, managed tool/write approval, cancellation, uncertain-execution recovery, immutable-image provenance and rollback |
| Deep Agents | Installed/selectable; one bounded guarded Test marker completed after Claude reconciliation with an exact result and matching guard/server/spend-log identity | Full authenticated delegation, HITL decision binding, subagent/tool limits, cancellation, uncertain-execution recovery, immutable-image provenance and rollback |
| OpenShell | CPU/source prerequisites and successor source tests | All 25 live gates, immutable image, exact worker identity, cancellation/recovery and rollback; current acceptance remains 0/25 |

This status table must be refreshed from actual runtime evidence after the remaining qualification work. A passing source test, CI workflow, Pod readiness flag, HTTP 200, or runtime being selectable is not equivalent to end-to-end acceptance.

## Sources

- [DSH three risk controls](THREE_RISK_CONTROLS.html)
- [DSH agent runtime and execution backends](AGENT_RUNTIME_AND_EXECUTION_BACKENDS.html)
- [DSH OpenShell prerequisites](OPENSHELL_RUNTIME_PREREQUISITES.md)
- [DSH security boundaries](SECURITY.md)
- [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)
- [Claude Code security](https://code.claude.com/docs/en/security)
- [Claude Code permissions](https://code.claude.com/docs/en/permissions)
- [Claude Code settings and precedence](https://code.claude.com/docs/en/settings)
- [Claude Code LiteLLM gateway configuration](https://docs.anthropic.com/en/docs/claude-code/llm-gateway)
- [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview)
- [Deep Agents backends](https://docs.langchain.com/oss/python/deepagents/backends)
- [Deep Agents human-in-the-loop](https://docs.langchain.com/oss/python/deepagents/human-in-the-loop)
- [Deep Agents profiles](https://docs.langchain.com/oss/python/deepagents/profiles)

