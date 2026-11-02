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
- [Claude Code security](https://code.claude.com/docs/en/security)
- [Claude Code permissions](https://code.claude.com/docs/en/permissions)
- [Claude Code settings and precedence](https://code.claude.com/docs/en/settings)
- [Claude Code LiteLLM gateway configuration](https://docs.anthropic.com/en/docs/claude-code/llm-gateway)
- [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview)
- [Deep Agents backends](https://docs.langchain.com/oss/python/deepagents/backends)
- [Deep Agents human-in-the-loop](https://docs.langchain.com/oss/python/deepagents/human-in-the-loop)
- [Deep Agents profiles](https://docs.langchain.com/oss/python/deepagents/profiles)

