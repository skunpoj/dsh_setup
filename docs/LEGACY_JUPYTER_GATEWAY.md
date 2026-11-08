# On-demand Jupyter for legacy owner workspaces

DSH2 and DSH3 open Jupyter when their existing owner chooses Jupyter. A stopped
server shows **Starting Jupyter**, then opens JupyterLab when ready. An existing
server and its kernels are reused. The existing usernames, passwords, Internet
approval and owner-only access remain authoritative. These legacy instances do
not gain a No Internet workspace from this change.

## Deployment boundary

The legacy login proxy shares a pod with the user's execution runtime. Replacing
that pod would end in-memory kernels. A separate, stateless transport gateway
therefore fronts each canonical site. The original authentication proxy remains
the only writer of its account and browser-session stores. The new gateway has
no password store, user workspace mount or Kubernetes service-account token.

The transport forwards ordinary HTTP and WebSocket traffic to a fixed existing
authentication service. For notebook startup it requires the original gateway's
actual JSON identity, the configured owner, Internet mode, a session-bound token
and the trusted origin. HTTP 200 containing a login form is not authentication.
Client headers and request bodies cannot select an owner, environment, host,
port, working directory or command.

The same fixed non-root Python launcher and controller used by Main DSH are
retained. Startup goes through the owner's existing authenticated terminal;
the execution runtime receives no new privileges. Administrator-disabled startup
is denied. Already enabled supervisor startup is awaited instead of duplicated.
Existing listeners, slow starts and kernels are never killed.

Each layer mounts only its owner's control directory, read-only. The underlying
CSI claim uses the normal existing attachment mode, while the container bind
mount and root filesystem remain read-only. Source files are an immutable
ConfigMap. Network policies allow the layer to reach only its own existing
authentication service on TCP 3080; public Internet and peer runtimes are not
new destinations for this transport. Canonical Ingress backend changes use
UID, resource-version and full-spec comparisons before replacing a single leaf.
Existing workspace Deployments, services, supervisors and login source stay
unchanged. Recovery restores only the original Ingress backend; it does not
restore an old account, notebook or history snapshot.

## Recorded qualification

Both exact-source synthetic legacy owner fixtures performed real cold startup,
three concurrent opens, Python execution yielding `42`, and a gateway-process
replacement while the same Jupyter server, kernel and variable persisted.

Both live sites reused their existing servers. A synthetic kernel WebSocket was
opened before cutover and the same connection, kernel and variable worked after
the route switch. Normal owner login, terminal, logout, anonymous denial,
cross-origin denial and cross-owner denial were verified. Existing notebook
files, user settings and saved histories were compared. No live server was
stopped to manufacture a cold-start test. Only the verification's synthetic
kernels were removed; IPython may record empty test-session metadata.

The private site profile records deployed resources
and recovery routing; it is operator evidence, not an automatic apply manifest.
