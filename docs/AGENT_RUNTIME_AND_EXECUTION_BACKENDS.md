# Agent runtime and execution backend

This reference separates the current product from the approved target design. It must not be read as evidence that the planned web task form is deployed.

## Available now

- Authenticated Web DSH, Web Terminal and the installed managed-client entry points operate in the user's assigned private workspace.
- DSH chat, DSH CLI/SDK entry points and Claude Code are distinct clients. An ordinary DSH chat prompt is not forwarded to another client.
- Azure source contains a guarded OpenShell complete-worker gateway hook. It is disabled by default and is not a current user-selectable backend.

## Candidate runtime choice - source implemented, not deployed

- **DSH Python SDK** will run the Python agent graph directly with a private SQLite checkpoint. SDK tool interrupts pause as `awaiting_approval`; the task resumes only after the user approves that paused action.
- **Claude Code** will run the managed coding-agent process in the selected project.

The browser does not run either client itself. The candidate authenticated task broker starts the selected runtime in the user's private execution boundary, streams persisted status and output, requires explicit task approval, supports cancellation, and records completion or interrupted recovery state. SDK tasks use resumable checkpoints and a separate approval for an interrupted tool action. All candidate runtimes use the bounded unattended launcher and guarded internal LiteLLM route. This describes reviewed source, not running Production behavior.

### Web DSH compared with the Python SDK

Web DSH is the authenticated control surface: it chooses the runtime, project, write mode and execution backend, then displays state and output. The DSH Python SDK is one runtime behind that control surface: it creates the programmatic agent, invokes tools, saves its checkpoint and resumes an approved interrupt. Choosing the SDK does not turn ordinary DSH chat into an SDK conversation and does not give the browser a model credential.

## Candidate execution-backend choice - not deployed

- **Private DSH workspace** will be the default and will remain available without OpenShell.
- **OpenShell isolated workspace** will be optional. It is unavailable until the current qualification record proves all 25 Test gates, rollback, namespace, node, resource budget and expiry.

OpenShell changes where approved tools execute; it does not bypass the model guard, select another model, expose credentials or grant cluster administration.

The immutable runtime image includes a pinned, checksum-verified `kubectl` client for Web Terminal and qualified execution backends. The client alone grants no cluster access: workspace Pods keep `automountServiceAccountToken: false`, and the image contains no default kubeconfig. An operator must provide a separately approved, least-privilege kubeconfig for a specific task. OpenShell receives the same client only through its qualified image and remains disabled until its 25 gates and rollback pass.

## Candidate web behavior - not deployed

The candidate `/agent-tasks` form shows two independent controls: `Agent runtime` and `Execution backend`. It also shows the selected project, task/write approval, streamed output, paused SDK approval and cancellation state. OpenShell is disabled with its exact qualification reason. The server validates every value; browser fields are not authorization. Image identity and model-ledger reconciliation remain operator evidence rather than browser assertions.

## Current acceptance boundary

The source candidate now contains the authenticated gateway, runtime broker, direct Python SDK runner, private SQLite checkpoints, SDK pause/resume approval, fixed Claude/Deep Agents launch mapping, persisted event polling, one-active-task admission, cancellation, restart interruption recovery, workspace confinement and an OpenShell-disabled capability. Offline source tests cover those boundaries. This does not establish immutable-image build, guarded client model behavior, private Test deployment, Production promotion or OpenShell acceptance. The web selectors become current user instructions only after bounded live acceptance, running-digest readback and affected-behavior verification all pass.
