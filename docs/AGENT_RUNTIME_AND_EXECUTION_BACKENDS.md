# Agent runtime and execution backend

This reference separates the deployed control plane from runtime capabilities that still require bounded live acceptance.

## Available now

- Authenticated Web DSH, Web Terminal and the installed managed-client entry points operate in the user's assigned private workspace.
- DSH chat, DSH CLI/SDK entry points and Claude Code are distinct clients. An ordinary DSH chat prompt is not forwarded to another client.
- The authenticated `/agent-tasks` broker is deployed. Its currently running capability endpoint advertises `sdk`, `claude` and `deepagents`; unauthenticated broker requests are rejected. The reviewed successor source adds `kilo` and one bounded, broker-owned handoff to a different runtime. That successor is source-tested but not yet deployed.
- Web Terminal includes a pinned, checksum-verified `kubectl` v1.32.9 client. The workspace has no automatic service-account token or default kubeconfig, so the binary does not itself grant cluster access.
- Azure source contains a guarded OpenShell complete-worker gateway hook. It is disabled by default and is not a current user-selectable backend.

## Deployed runtime choices and acceptance status

- **DSH Python SDK** is exposed by the deployed broker. Its implementation runs the Python agent graph with a private SQLite checkpoint; SDK tool interrupts pause as `awaiting_approval` and resume only after approval.
- **Claude Code** is exposed by the deployed broker and maps to the managed coding-agent launcher in the selected project.
- **Deep Agents** is exposed by the deployed broker and maps to the installed managed runtime.
- **Kilo** is installed. The reviewed successor broker exposes its non-interactive `--pure run` path through the same one-start guard; the currently running broker does not yet advertise it.
- **TrueForge** remains an owner-only private web application inside the DSH workspace. It is not another DSH and is not a command-line broker runtime. A future HTTP adapter may bind it to the same broker lifecycle without creating a second task writer or credential store.

The browser does not run a client itself. The authenticated task broker starts the selected runtime in the user's private execution boundary, streams persisted status and output, requires explicit task approval, supports cancellation, and records completion or interrupted recovery state. SDK tasks use resumable checkpoints and a separate approval for an interrupted tool action. The broker's live health, authentication boundary and advertised capability mapping are verified. Guarded live model execution for each advertised runtime has not yet been accepted and must not be inferred from the capability response.

The successor source can pass the bounded captured output of one successful runtime to one different runtime. Each stage receives a separate opaque correlation ID, is limited to one model start, and routes through the same guard. The broker stores runtime, project, state and correlation metadata but not the prompt. Source tests prove command construction, handoff, duplicate suppression, correlation injection and cancellation primitives; they do not prove the successor image is running or that two live agents completed a handoff.

## Component model

```text
Web DSH (authentication, workspace, history, task lifecycle)
└─ /agent-tasks broker — sole task writer
   ├─ runtimes: DSH Python SDK, Claude Code, Deep Agents, Kilo
   ├─ optional application adapter: TrueForge
   └─ backend: private DSH workspace or qualified OpenShell

Every model start
└─ per-stage guard and correlation ledger
   └─ internal LiteLLM
      └─ deepinfer-dspark
```

Runtime answers **which agent performs the task**. Backend answers **where its approved tools execute**. TrueForge is an alternative private user interface, while OpenShell is an optional isolation backend; neither replaces Web DSH's authenticated platform boundary.

### Web DSH compared with the Python SDK

Web DSH is the authenticated control surface: it chooses the runtime, project, write mode and execution backend, then displays state and output. The DSH Python SDK is one runtime behind that control surface: it creates the programmatic agent, invokes tools, saves its checkpoint and resumes an approved interrupt. Choosing the SDK does not turn ordinary DSH chat into an SDK conversation and does not give the browser a model credential.

## Execution-backend choice

- **Private DSH workspace** is the deployed default and remains available without OpenShell.
- **OpenShell isolated workspace** is an optional target design. It is unavailable until the qualification record proves all 25 Test gates, rollback, namespace, node, resource budget and expiry.

OpenShell changes where approved tools execute; it does not bypass the model guard, select another model, expose credentials or grant cluster administration.

The immutable runtime image includes a pinned, checksum-verified `kubectl` client for Web Terminal and qualified execution backends. The client alone grants no cluster access: workspace Pods keep `automountServiceAccountToken: false`, and the image contains no default kubeconfig. An operator must provide a separately approved, least-privilege kubeconfig for a specific task. OpenShell receives the same client only through its qualified image and remains disabled until its 25 gates and rollback pass.

## Deployed web behavior

The deployed `/agent-tasks` form shows two independent controls: `Agent runtime` and `Execution backend`. It also shows the selected project, task/write approval, streamed output, paused SDK approval and cancellation state. OpenShell is disabled with its exact qualification reason. The server validates every value; browser fields are not authorization. Image identity and model-ledger reconciliation remain operator evidence rather than browser assertions.

## Current acceptance boundary

The authenticated gateway and current broker are deployed with direct Python SDK runner source, private SQLite checkpoints, SDK pause/resume approval, fixed Claude/Deep Agents launch mapping, persisted event polling, one-active-task admission, cancellation, restart interruption recovery, workspace confinement and an OpenShell-disabled capability. The reviewed successor source adds Kilo, bounded cross-runtime handoff and end-to-end correlation metadata. Its source checks pass, but no successor image, Test deployment or live handoff has yet been verified. Guarded live model behavior, guard-to-LiteLLM reconciliation, TrueForge adapter behavior and OpenShell's 25-gate acceptance remain unverified. Do not describe those items as complete until bounded live acceptance and affected-behavior verification pass.
