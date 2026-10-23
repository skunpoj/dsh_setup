# Enable Jupyter autostart in existing Internet workspaces

This is a one-time operator migration for private Internet workspaces that have an existing service policy without a Jupyter definition. New-user provisioning already seeds the default in both environments. It creates that default only when the policy file is absent, so it cannot undo Admin Stop or an administrator's customized services.

## Before changing settings

1. Identify the intended private Internet runtime and its service-control key. Do not derive ownership from a display name alone.
2. Read its current config.json and record the SHA-256 of its exact bytes. Review its Internet entitlement, existing services and current Jupyter process. Preserve any existing Jupyter definition, including a disabled one.
3. Save the reviewed keys and hashes as a bounded JSON plan. Each row has key and sha256 fields. The tool accepts at most 64 reviewed entries per invocation; this is a maintenance batch limit, not a user or URL quota.
4. Prepare a private operator backup directory and the existing central application audit destination. Keep credentials, account stores, notebooks and histories outside the migration workload's mounts.

## Dry run and apply

Run scripts/backfill_jupyter_autostart.py with --root pointing to the service-control directory, --plan to the reviewed JSON plan, --backup to a new private backup directory, and --audit-file to the protected audit file. Without --apply it only reports eligible and preserved definitions. Review that list before repeating the same invocation with --apply.

The new definition is named jupyter, runs the fixed jupyter lab command in /workspace, uses port 8888, and is enabled at generation 1. It retains the existing allowed value and every other service. It never signals an application process. Existing Jupyter definitions are skipped rather than reset.

Run the migration in a narrow, non-root operator workload with no Kubernetes token, no network access, no elevated capabilities and no workspace/history/credential mounts. Mount only the policy directory, the protected new backup subdirectory, the audit subdirectory and the reviewed source. Keep an immutable copy of the source and plan with the operator receipt.

## Verify the result

1. Read each saved definition back and compare its unchanged Internet entitlement and other services. Check original backup hashes and requested/applied audit records. A second dry run must report no eligible policies and preserve all existing Jupyter definitions.
2. For approved Internet workspaces, inspect the supervisor and the actual listening server. An already-running on-demand server must retain its process and kernels. **Waiting for existing Jupyter** is expected until natural handover; never stop active notebooks to make the status look clean.
3. For workspaces without Internet approval, confirm **Internet approval pending** and no new server. Do not grant Internet merely to test startup.
4. Qualify full replacement and Stop persistence on disposable private runtimes using synthetic notebooks, settings and native DSH histories. Verify autostart before opening Jupyter, then compare saved file hashes across replacements. Do not replace active production runtimes for this test.
5. Remove only the task's temporary test and operator workloads. Retain the private original-policy backups and central audit records.

## If a change conflicts or fails

The migration refuses unsafe files, changed hashes, detected concurrent edits, a full service limit or unavailable audit output. Inspect the saved result and re-review any remaining policies. Do not blindly restore an old policy after new notebook work has begun: changing desired state can end a managed process. Use the dashboard and a controlled owner handover when a running service genuinely needs to be stopped.

## Preservation and resource use

Saved notebooks, Jupyter preferences, private workspace files and DSH histories remain on their existing volumes. The policy change neither moves them nor changes user/environment routing. Saved content survives replacement; unsaved variables and kernel memory do not. Autostart keeps an idle server resident, so Stop remains an administrator's resource-control option.

[Lifecycle guide](JUPYTER_APP_LIFECYCLE.html) · [Start controls](JUPYTER_START_CONTROLS.html) · [Walkthrough](JUPYTER_DSH2_DSH3_WALKTHROUGH.html)
