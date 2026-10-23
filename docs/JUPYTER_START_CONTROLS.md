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
