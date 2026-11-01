# Agent runtime and execution backend

This reference separates the current product from the approved target design. It must not be read as evidence that the planned web task form is deployed.

## Available now

- Authenticated Web DSH, Web Terminal and the installed managed-client entry points operate in the user's assigned private workspace.
- DSH chat, DSH CLI/SDK entry points and Claude Code are distinct clients. An ordinary DSH chat prompt is not forwarded to another client.
- Azure source contains a guarded OpenShell complete-worker gateway hook. It is disabled by default and is not a current user-selectable backend.

## Runtime choice

- **DSH Python SDK** runs programmatic DSH workflows, tools and event streams.
- **Claude Code** runs the managed coding-agent process in the selected project.

The browser does not run either client itself. The authenticated task broker starts the selected runtime in the user's private execution boundary, streams status and output, handles approval and cancellation, and records the final result. Both runtimes use the same task admission guard and internal LiteLLM route.

## Execution-backend choice

- **Private DSH workspace** is the default and remains available without OpenShell.
- **OpenShell isolated workspace** is optional. It is unavailable until the current qualification record proves all 25 Test gates, rollback, namespace, node, resource budget and expiry.

OpenShell changes where approved tools execute; it does not bypass the model guard, select another model, expose credentials or grant cluster administration.

## Target web behavior - not deployed

The planned task form shows two independent controls: `Agent runtime` and `Execution backend`. It also shows the selected project, environment, allowed tools, image identity, limits, approvals, live output, cancellation state and cleanup result. An unavailable backend is disabled with the exact reason. The server validates every value; browser fields are not authorization.

## Current acceptance boundary

The immutable candidate runtime contains the official SDK and guarded Claude launcher. The SDK has one successful guarded Test turn. That does not establish the planned web broker, guarded Claude acceptance, Production promotion or OpenShell acceptance. OpenShell remains disabled until its separate qualification passes. The web selectors become user documentation only after source tests, immutable-image build, private Test deployment, bounded live acceptance, running-digest readback and affected-behavior verification all pass.
