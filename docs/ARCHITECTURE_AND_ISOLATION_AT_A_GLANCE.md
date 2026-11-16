# Architecture and isolation at a glance

Current consolidated guidance: [central index](index.html), [canonical guide](DSH_CURRENT_GUIDE.html#canonical-reading), [architecture and two SVG maps](ARCHITECTURE_AND_ISOLATION_AT_A_GLANCE.html), and [three control layers](THREE_RISK_CONTROLS.html). Older source observations below keep their original dates and are not fresh runtime acceptance.


Status as of 15 November 2026. Five diagrams show how the platform is built and where its isolation boundaries are. Every box is labelled **live**, **decided, not yet live** or **disabled**; one path carries a narrower label, "live on the test runtime 7528dfdf; rest of the fleet at promotion". The diagrams are drawn in the HTML page; the tables below list the same boxes in text, with the page they rest on. Sources are cited by file name.

## 1. The platform

| Box | State | Rests on |
|---|---|---|
| Browser, then dsh-gateway (login, landing, /api/status, owner-bound routing) | live | `DSH_NETWORK_ZONES.html`, `APP_SERVICE_SUPERVISION.html` |
| Per-user workspace pods: No Internet and Internet, one pair per user | live | `APP_SERVICE_SUPERVISION.html` |
| Filtered DNS for the No Internet pods | live | `DSH_NETWORK_ZONES.html` |
| litellm-gateway and guard (context 393,216, output 8,192, reserve 256, 16 long requests and 16 waiters), then context-forwarder | live | `PLATFORM_CAPACITY_AND_CLIENTS.html`, `DSH_NETWORK_ZONES.html` |
| DeepSeek on four GPUs (deepinfer-dspark), 393,216-token context, 16 sequence slots | live | `PLATFORM_CAPACITY_AND_CLIENTS.html` |
| ASR workers (GPU) | live | `diagrams/multiharness-component-deployment-map.svg` |
| sglang-dspark | disabled (stopped alternate) | `DSH_NETWORK_ZONES.html` |
| DSH documentation library at /manual/, served by the gateway | live | `DSH_NETWORK_ZONES.html` |

The diagram does not draw the route to the ASR workers; see the SMP stress report for that path.

## 2. The workspace pod

| Box | State | Rests on |
|---|---|---|
| init container: prepares private storage (ownership of /state and /workspace), then exits | live | `APP_SERVICE_SUPERVISION.html` |
| dsh (main container): web chat, Web Terminal, agents (Claude Code, Deep Agents, DSH Python SDK, Kilo), /state, credentials | live | `AGENT_RUNTIME_AND_EXECUTION_BACKENDS.html`, `APP_SERVICE_SUPERVISION.html` |
| app-supervisor (sidecar): JupyterLab and its terminal; read-only root; mounts only /workspace, /packages/approved and /state/jupyter plus its own control and status volumes; HOME /tmp/service-home; no credentials | live (isolated today) | `APP_SERVICE_SUPERVISION.html` |
| Parity change (1): agent state and the read-only credentials mounted into the sidecar | decided, not yet live | the user's decision, being implemented |
| Parity change (2): tools synced from the main container to the sidecar at promotion | decided, not yet live | the user's decision, being implemented |

Today the sidecar shares the pod network rules, the owner workspace and the approved package cache with the main container, and nothing else. It receives no GPU, no Kubernetes token, no gateway account store and no model API key.

## 3. The agent task path

| Box | State | Rests on |
|---|---|---|
| Chat, then `dsh-agent-task --propose`, then a confirmation card, then a signed receipt | live on the test runtime 7528dfdf; rest of the fleet at promotion | ledger row A2A-LANE-6-CELL-MATRIX-FINAL-VERDICT-20261115 (six-cell matrix PASS, 15 November 2026); `A2A_TASK_DELEGATION.html` still shows chat delegation as being built |
| Broker at /agent-tasks (authenticated; explicit task approval), reachable from the form | live | `AGENT_RUNTIME_AND_EXECUTION_BACKENDS.html` |
| Guard ledger: model-start cap of 1 to 32 per task, written to model-starts.jsonl | live | `A2A_TASK_DELEGATION.html` |
| Agent runtime (sdk, claude or deepagents) in the user's private workspace | live | `AGENT_RUNTIME_AND_EXECUTION_BACKENDS.html` |
| Direct Web Terminal run: the per-task cap and ledger do not apply (finding F1) | live, not guarded per task | the team's task records |

A run through the broker is limited by the per-task cap. A run started by hand in the Web Terminal is not; the shared model gateway limits still apply to every request.

## 4. Network policy and zones

| Box | State | Rests on |
|---|---|---|
| No Internet workspace: direct Internet blocked by policy; filtered DNS and the internal model route only | live | `DSH_NETWORK_ZONES.html` |
| Internet workspace: separate runtime and volumes, public-network access, no mount of No Internet data | live | `DSH_NETWORK_ZONES.html` |
| Approved package cache: read-only in the restricted workers; promotion is separately controlled | live | `DSH_NETWORK_ZONES.html` |
| Internal model route: model and database outbound denied | live | `DSH_NETWORK_ZONES.html` |
| Identity connector (optional): LDAPS 636 from the gateway only | live | `DSH_NETWORK_ZONES.html` |
| Enterprise integrations: exact approved destinations through the proxy | decided, not yet live | `DSH_NETWORK_ZONES.html` (needs site-approved integration) |

Physical DMZ and VLAN placement has not been confirmed against the enterprise network record. No Internet and Internet are separate execution-policy environments; their names do not establish separate physical VLANs. Enforcement is claimed only as far as the evidence on `DSH_NETWORK_ZONES.html` goes.

## 5. Where OpenShell plugs in

| Box | State | Rests on |
|---|---|---|
| /agent-tasks form with its Execution backend selector, and the authenticated broker | live | `AGENT_RUNTIME_AND_EXECUTION_BACKENDS.html` |
| Private DSH workspace backend (the default) | live | `AGENT_RUNTIME_AND_EXECUTION_BACKENDS.html` |
| OpenShell isolated workspace backend | disabled | `OPENSHELL_STATUS_AND_USAGE.html`, `OPENSHELL_RUNTIME_PREREQUISITES.html` |
| Native SDK zero-start qualification: PASS for pair f10b48e3 and for pair 2e0966c2, each for itself only | live (evidence) | `OPENSHELL_STATUS_AND_USAGE.html` |
| OpenShell backend qualification: the 25 Test gates and rollback receipts have not been run | disabled | `OPENSHELL_RUNTIME_PREREQUISITES.html` |

OpenShell changes where approved tools run. It does not bypass the model guard, select another model, expose credentials or grant cluster rights. The page OpenShell and the native SDK qualification (not included in this public source projection) gives the full digests and the run records.

## Related pages

- Managed Jupyter and application startup (not included in this public source projection)
- [DSH network zones](DSH_NETWORK_ZONES.html)
- [Agent runtime and execution backend](AGENT_RUNTIME_AND_EXECUTION_BACKENDS.html)
- Agent-to-agent task delegation (not included in this public source projection)
