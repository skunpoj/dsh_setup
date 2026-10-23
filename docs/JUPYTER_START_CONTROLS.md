# Jupyter Start and administrator controls

## Start without interrupting an open notebook

**Start is safe to repeat.** When a managed Jupyter service is already enabled,
Start leaves its process, restart counter and saved service settings unchanged.
The dashboard reports: "Service is already enabled. Its process and settings
were left unchanged." Existing notebooks and kernel variables remain available.

An enabled service that is recovering remains under its existing supervisor;
Start does not force a restart or reset recovery. Check the displayed status.

| Action | Effect | Running kernels |
| --- | --- | --- |
| Start, already enabled | No service-file write or restart-counter change | Continue unchanged |
| Start, stopped | Enables the existing service; the supervisor starts it | A new server becomes available |
| Restart | Explicitly replaces the supervised process | Interrupted; save work first |
| Stop | Disables automatic startup and stops the managed process | Interrupted; save work first |

## Administrator steps

1. Open **Admin overview**, then **Managed startup services**.
2. Locate the Jupyter row for the intended runtime, owner and environment.
   Main DSH has private owner/environment pairs. DSH2 and DSH3 use their
   designated owner and assigned Internet environment.
3. Click **start**. Repeating Start does not ask for a destructive-action
   confirmation. An already-enabled service returns the unchanged message.
4. If the service was stopped, wait for its status to become **running**, then
   open JupyterLab. Opening Jupyter also reuses an existing server.
5. Use **restart** or **stop** only when interruption is intended. These actions
   retain their confirmation prompts. Saving a changed running service definition
   may also replace its process; do not use Save as a substitute for Start.

Notebooks, settings and DSH histories remain in their existing private storage.
Start does not move or copy them. Saving files provides persistence; kernel
variables are in-memory state and do not survive a full workspace restart.

[User manual](DSH_USER_MANUAL.html) ·
[Captioned Start walkthrough](JUPYTER_DSH2_DSH3_WALKTHROUGH.html) ·
[Opening Jupyter](JUPYTER_ON_DEMAND.md)

[Stop, Restart and automatic startup for Jupyter and managed apps](JUPYTER_APP_LIFECYCLE.html)

## Existing on-demand server

If the dashboard reports **Waiting for existing Jupyter**, a server started before managed autostart may still be running. Leave it in place while notebooks are active. The supervisor waits for its natural exit and then launches the enabled managed service. Stop disables future startup but does not stop this unowned server during the handover.

[Autostart defaults and Internet approval](JUPYTER_APP_LIFECYCLE.html) · [Operator backfill procedure](JUPYTER_AUTOSTART_BACKFILL.html)

**Internet approval pending** means the account is enabled but its Internet environment is not approved. It is different from **Account disabled**. Failed startup retries remain **Recovery retry pending**, rather than being described as an existing server.

## What happens when the condition changes?

| Before | What changes | Expected dashboard result |
| --- | --- | --- |
| Waiting for existing Jupyter | The existing server exits naturally and releases port 8888 | Managed Jupyter starts automatically; the label changes to **Running** |
| Internet approval pending | An administrator chooses **User management → Allow Internet** for that user | The approval label clears; an enabled Jupyter service starts, or shows **Waiting for existing Jupyter** if another server holds its port |

Allow Internet grants environment access; it does not override a service disabled with **Stop**. A running account's No Internet access is independent of this approval. The display follows the next permission reconciliation and supervisor/status refresh; it is not an instantaneous browser-only switch. Use **Refresh** to read the latest state.

Do not stop an active server just to clear a waiting label. Save work and let its owner close the server when appropriate. Closing a browser tab alone may leave the server running. Automatic handover starts a new server: saved notebooks and preferences remain, while kernel variables from the exited server do not transfer.
