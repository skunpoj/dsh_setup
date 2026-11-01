# Agent runtime and execution backend

This reference separates the current product from the approved target design. It must not be read as evidence that the planned web task form is deployed.

## Available now

- Authenticated Web DSH, Web Terminal and the installed managed-client entry points operate in the user's assigned private workspace.
- DSH chat, DSH CLI/SDK entry points and Claude Code are distinct clients. An ordinary DSH chat prompt is not forwarded to another client.
- Azure source contains a guarded OpenShell complete-worker gateway hook. It is disabled by default and is not a current user-selectable backend.

## Candidate runtime choice - source implemented, not deployed

- **DSH Python SDK** will run programmatic DSH workflows, tools and event streams.
- **Claude Code** will run the managed coding-agent process in the selected project.

The browser does not run either client itself. The candidate authenticated task broker starts the selected runtime in the user's private execution boundary, streams persisted status and output, requires explicit task approval, supports cancellation, and records completion or interrupted recovery state. Both candidate runtimes use the bounded unattended launcher and internal LiteLLM route. This describes reviewed source, not running Production behavior.

## Candidate execution-backend choice - not deployed

- **Private DSH workspace** will be the default and will remain available without OpenShell.
- **OpenShell isolated workspace** will be optional. It is unavailable until the current qualification record proves all 25 Test gates, rollback, namespace, node, resource budget and expiry.

OpenShell changes where approved tools execute; it does not bypass the model guard, select another model, expose credentials or grant cluster administration.

## Candidate web behavior - not deployed

The candidate `/agent-tasks` form shows two independent controls: `Agent runtime` and `Execution backend`. It also shows the selected project, write approval, streamed output and cancellation state. OpenShell is disabled with its exact qualification reason. The server validates every value; browser fields are not authorization. Image identity and model-ledger reconciliation remain operator evidence rather than browser assertions.

## Current acceptance boundary

The source candidate now contains the authenticated gateway, runtime broker, fixed SDK/Claude/Deep Agents launch mapping, persisted event polling, one-active-task admission, cancellation, restart interruption recovery, workspace confinement and an OpenShell-disabled capability. Offline source tests cover those boundaries. This does not establish immutable-image build, guarded client model behavior, private Test deployment, Production promotion or OpenShell acceptance. The web selectors become current user instructions only after bounded live acceptance, running-digest readback and affected-behavior verification all pass.
