# Agent runtime and execution backend

This reference separates the deployed control plane from runtime capabilities that still require bounded live acceptance.

## Available now

- Authenticated Web DSH, Web Terminal and the installed managed-client entry points operate in the user's assigned private workspace.
- DSH chat, DSH CLI/SDK entry points and Claude Code are distinct clients. An ordinary DSH chat prompt is not forwarded to another client.
- The authenticated `/agent-tasks` broker is deployed. Its live capability endpoint advertises `sdk`, `claude` and `deepagents`; unauthenticated broker requests are rejected.
- Web Terminal includes a pinned, checksum-verified `kubectl` v1.32.9 client. The workspace has no automatic service-account token or default kubeconfig, so the binary does not itself grant cluster access.
- Azure source contains a guarded OpenShell complete-worker gateway hook. It is disabled by default and is not a current user-selectable backend.

## Deployed runtime choices and acceptance status

- **DSH Python SDK** is exposed by the deployed broker. Its implementation runs the Python agent graph with a private SQLite checkpoint; SDK tool interrupts pause as `awaiting_approval` and resume only after approval.
- **Claude Code** is exposed by the deployed broker and maps to the managed coding-agent launcher in the selected project.
- **Deep Agents** is exposed by the deployed broker and maps to the installed managed runtime.

The browser does not run a client itself. The authenticated task broker starts the selected runtime in the user's private execution boundary, streams persisted status and output, requires explicit task approval, supports cancellation, and records completion or interrupted recovery state. SDK tasks use resumable checkpoints and a separate approval for an interrupted tool action. The broker's live health, authentication boundary and advertised capability mapping are verified. Guarded live model execution for each advertised runtime has not yet been accepted and must not be inferred from the capability response.

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

The authenticated gateway and broker are deployed with direct Python SDK runner source, private SQLite checkpoints, SDK pause/resume approval, fixed Claude/Deep Agents launch mapping, persisted event polling, one-active-task admission, cancellation, restart interruption recovery, workspace confinement and an OpenShell-disabled capability. The immutable runtime image and running digest are verified, as are broker health and authentication boundaries. Guarded live model behavior for `sdk`, `claude` and `deepagents`, model-ledger reconciliation, and OpenShell's 25-gate acceptance remain unverified. Do not describe those items as complete until bounded live acceptance and affected-behavior verification pass.
