# Open Jupyter when needed

Main DSH starts Jupyter when its owner opens the Jupyter button in the selected
Internet or No Internet workspace. This is the default behavior for Main accounts;
it does not grant Internet approval or change administrator service restrictions.

If Jupyter already responds, the gateway forwards the request without launching,
restarting or stopping a server or kernel. If stopped, the owner sees a
**Starting Jupyter** page. A same-origin, session-bound POST requests startup,
then the page opens JupyterLab when its actual HTML is ready. A bounded failure
shows a retry option instead of claiming readiness or stopping another process.

This is startup on opening Jupyter, not startup for every account at login or
workspace boot. No idle shutdown policy is introduced. Restarting an entire user
workspace still ends its in-memory processes; durable notebooks and files persist.

## Implementation and boundaries

- The gateway derives owner and environment from the authenticated session.
  Clients cannot supply a host, owner, environment, command, working directory
  or request body. Account stamp, session expiry/revocation and Internet approval
  are rechecked during the asynchronous operation.
- The fixed launcher runs under the owner's existing non-root terminal service.
  No Kubernetes credentials or new privileges are supplied to the gateway.
- A private, no-follow lock and PID/start-time record deduplicate requests within
  the runtime; the gateway also coalesces simultaneous requests. Existing listeners
  and slow starts are never killed. An administrator-managed enabled Jupyter is
  awaited instead of launching another managed service.
- The launcher uses only the root-installed Jupyter executable and its Python.
  It does not edit notebooks, histories, passwords, permissions, mappings or
  persistent service-enabled settings. Normal Jupyter initialization may create
  its own configuration/runtime metadata and empty IPython session records.
- The deployment changes only Main's gateway source ConfigMap reference. User
  pods and app supervisors must not restart. Existing browser sessions persist.
  Source-only rollback must retain the current persistent data, accounts, courses
  and manuals; it must never restore an old data snapshot.

## Qualification

Automated coverage includes existing-server reuse, concurrent opening, private
runtime separation, expired/revoked/account-changed sessions, CSRF/origin/body
rejection, disabled services, bounded failure and launcher packaging. Linux tests
exercise private file modes, symbolic/hard links, FIFOs and stale PID handling.
Runtime qualification must also demonstrate a real kernel calculation after cold
startup and a held kernel/variable surviving the gateway-only replacement.

Recorded acceptance belongs to its deployed source hash; tests do not establish
that every user account or future workspace restart was interactively exercised.
