# Jupyter and managed application lifecycle

Use **Admin overview → Managed startup services** to manage a service in one user's selected environment. Check the owner, runtime and environment before making a change. The same service controls are available for the assigned DSH2 and DSH3 owners.

## Understand the dashboard status

| Label | Meaning | Administrator action |
| --- | --- | --- |
| Waiting for existing Jupyter | A pre-existing server holds the notebook port; managed startup waits for natural handover | Leave active notebooks running. Managed startup resumes after that server exits |
| Internet approval pending | The account is enabled, but Internet access has not been approved | Use User management → Allow Internet only when approval is intended |
| Account disabled | The whole account has been disabled | Review account access separately from Internet approval |
| Recovery retry pending | A managed process failed or exited and the supervisor is waiting before retrying | Inspect the failure; this does not mean an existing notebook server was found |
| Startup failed | The last start attempt failed | Inspect the service command, dependencies and runtime |

These labels describe status; they do not change service settings or permissions. Raw machine phases remain available for diagnostics. A missing or stale status is shown as unavailable rather than healthy. Closing a browser tab does not necessarily end the Jupyter server, so it may continue waiting until the server itself exits.

## What happens when the condition changes?

| Before | What changes | Expected dashboard result |
| --- | --- | --- |
| Waiting for existing Jupyter | The existing server exits naturally and releases port 8888 | Managed Jupyter starts automatically; the label changes to **Running** |
| Internet approval pending | An administrator chooses **User management → Allow Internet** for that user | The approval label clears; an enabled Jupyter service starts, or shows **Waiting for existing Jupyter** if another server holds its port |

Allow Internet grants environment access; it does not override a service disabled with **Stop**. A running account's No Internet access is independent of this approval. The display follows the next permission reconciliation and supervisor/status refresh; it is not an instantaneous browser-only switch. Use **Refresh** to read the latest state.

Do not stop an active server just to clear a waiting label. Save work and let its owner close the server when appropriate. Closing a browser tab alone may leave the server running. Automatic handover starts a new server: saved notebooks and preferences remain, while kernel variables from the exited server do not transfer.

## What each control does

| Control | Running process | Saved setting after a workspace replacement |
| --- | --- | --- |
| Start | Enables a stopped service; an already-enabled service stays unchanged | Enabled services start automatically when access is allowed |
| Stop | Stops the managed process and its child processes | Disabled; stays stopped until an administrator starts it |
| Restart | Replaces the managed process | Enabled; the replacement starts under the supervisor |
| Save service definition | Saves the command, working directory and approved port | An enabled changed definition may replace its process |

**Save notebooks and application data before Stop or Restart.** Jupyter kernels, variables and unsaved application memory end with their processes. Files that have been saved in durable storage remain available. Saving a changed running definition is an administrative change, not a substitute for Start.

## Manage Jupyter

1. Open **Admin overview**, then **Managed startup services**.
2. Select the intended owner, runtime and environment. Locate **jupyter**.
3. Use **start** to enable Jupyter. Repeated Start leaves an already-enabled service unchanged, including its restart generation.
4. Wait for **running**, then open JupyterLab. A loading page alone does not prove that the server is ready.
5. Use **stop** to disable Jupyter. Opening the Jupyter page cannot override Admin Stop; its launch request is refused while the service is disabled.
6. Use **restart** only when replacing the server and ending its kernels is intended. Reopen saved notebooks after the new server is ready.

Newly assigned private workspaces have a default managed Jupyter service in both No Internet and Internet environments. No Internet is available after signup. Internet Jupyter starts only after an administrator grants Internet access; enabling its service does not grant that permission. A workspace replacement starts a new server; it does not restore the previous kernel's variables.

## Why enable automatic startup?

Jupyter already works on demand when the user opens it. Automatic startup removes the need to reopen the launcher after a workspace replacement and gives administrators a persistent desired state. It uses CPU and RAM while idle; it does not allocate another GPU model. Administrators can use Stop to opt out, and the disabled setting survives replacement.

New-user provisioning seeds a default only when no service-policy file exists. It deliberately preserves existing settings, including Admin Stop. Older Internet workspaces with an existing empty service policy therefore need a one-time addition; a normal provisioner refresh must not reset their policies.

## Add autostart without interrupting an existing server

When a previously on-demand Jupyter server is already using port 8888, the supervisor waits and reports **Waiting for existing Jupyter**. It does not adopt the server, launch a duplicate or end its kernels. Automatic management takes over after that server exits naturally. An administrator must not use Restart to force the handover while someone is working.

While waiting for that handover, Stop disables future automatic startup; it does not terminate the pre-existing, unmanaged server. Start is safe to repeat for the saved managed definition. Save a changed definition or use Restart only when ending the managed process is intended.

The startup setting is separate from Internet approval and from private storage. No files, histories or credentials are copied between users or environments by enabling it.

## Register an application for automatic startup

1. Save the application source and its data under the user's private `/workspace`. For persistent preferences, configure the application to save them there too; arbitrary files in `/tmp` or a container-only home are temporary.
2. In **My applications**, create the application's private URL mapping and choose the port on which it listens. Creating a URL alone does not launch a process.
3. Ask an administrator to locate that owner and environment in **Managed startup services**. Save a **command** service using the application's mapped name, a working directory inside `/workspace`, and an argument array for its workspace script.
4. For example, a saved Python application can use `['python3', '/workspace/my_app.py']` and listen on the port in its URL mapping. Enter a JSON array in the dashboard: `["python3","/workspace/my_app.py"]`. Node workspace scripts and named `npm run` scripts are also supported. The runtime must already contain their dependencies.
5. Click **start**, wait for **running**, then open the application URL and inspect its actual response.
6. Use **stop** or **restart** on that service without changing another user's environment. Its saved files stay in its private workspace.

The supervisor runs approved commands without a shell. Up to four managed services are supported per environment, including Jupyter. Application URL quotas are separate from this managed-process limit. An unmanaged process started manually in a terminal is not automatically relaunched merely because it has a URL.

## Automatic startup and recovery

The gateway stores the desired service state. The private runtime's supervisor checks it every few seconds and starts enabled services only when environment access is allowed. Services disabled with Stop remain disabled after runtime replacement. An enabled process that exits is retried with bounded backoff; a busy port is reported rather than launching a second process on it. Repeated Start does not reset that recovery loop.

Private storage retains saved notebooks, Jupyter preferences, application source/data, service definitions and DSH histories. Each has its own role: the service definition controls startup; durable files hold saved work; kernel/process memory is temporary. A replacement is not a backup or a way to recover unsaved work.

## Disposable acceptance checks

Two fresh signup users were tested using the deployed gateway and supervisor source with separate disposable volumes. Stop and Restart were exercised through authenticated admin endpoints. Both enabled services started automatically after replacement, before any Jupyter launch-page request. Disabled services remained stopped across a further replacement. Saved notebook content, Jupyter theme, application source/data and native DSH history were reopened and compared across replacements. These checks used synthetic data and no model requests; active user notebooks were not restarted.

[User manual](DSH_USER_MANUAL.html) · [Start controls](JUPYTER_START_CONTROLS.html) · [Captioned lifecycle walkthrough](JUPYTER_DSH2_DSH3_WALKTHROUGH.html)

[Operator procedure for existing Internet workspaces](JUPYTER_AUTOSTART_BACKFILL.html)
