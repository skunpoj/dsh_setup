# First-come, first-reserved workspaces

## What changes for people

| | Before | After |
|---|---|---|
| Account limit | `maxAccounts` 32, plus a 32-slot inventory | No account limit. An account holds storage only. |
| When compute is reserved | At signup, permanently, as a running pair | Only while you use it: your workspace starts when you sign in and resources allow |
| When it's released | Never, except a manual admin stop | On sign-out, or after 60 min without activity. Your files stay. |
| Node full | New signups refused; existing users unaffected | Sign-ins wait in a first-come queue with a self-refreshing page |
| Visibility | "N new-user slots available" | The sign-in page shows live shared-resource status for everyone |
| Spare workspaces | 2 running pairs (~1.1 CPU reserved) | Qualified once, then **stopped**: storage only, no compute |

Cold start: a stopped workspace takes roughly 30–60 s to start. That is the accepted trade-off for not reserving resources.

## How it works

1. **Gateway** (`scripts/session_demand.js`, wired into `auth_proxy.js`). Every authenticated request, application visit and browser
   WebSocket byte marks the user's private runtime as in use. Every 5 s the gateway writes `policy/demand.json` on the capacity volume:
   runtime Deployment names with the first-request time and last-activity time, no user names. Sign-out removes the entry at once; idle
   entries drop out after `DSH_SESSION_IDLE_MINUTES` (default 60). After a restart the gateway reloads the file, so a restart never
   stops working users. On the very first rollout, everyone already signed in is treated as active for one idle period.
2. **Controller** (`scripts/capacity_session.py`, `capacity_controller.sessions()`). Each round, before provisioning:
   - **Starts** demanded runtimes that are stopped, earliest request first, up to the number that fit now: one runtime needs half a
     pair budget of CPU, memory and pods after the protected reserve. Disk never blocks a start, because storage already exists. At most
     4 starts per round.
   - **Stops** running runtimes that no signed-in user is using. A pair still being prepared or qualified is never touched.
   - **Fails safe:** if the gateway's demand file is missing or stale (> 60 s), nothing is stopped and nothing new is started.
   - Writes `inventory/sessions.json` (each runtime's state and queue position, plus an aggregate). The loop runs every 5 s while
     someone is starting or waiting, and every 15 s otherwise.
   - The only new Kubernetes permission is `get/patch` on `deployments/scale`, plus `list` on deployments. `Kube.scale()` refuses any
     name other than `dsh-u-<16 hex>-(secure|internet)` and any replica count other than 0 or 1. It never edits templates, storage or
     credentials.
3. **Gateway reads `sessions.json`:**
   - stopped / stopping / starting / waiting: a browser gets a waiting page (refresh 5 s, queue position, live numbers, no script); an
     API client gets `503` with `Retry-After: 5`; a WebSocket is refused with `503 RUNTIME_STARTING`.
   - running, or controller state unknown or stale: proxies as before. A controller outage never locks out a running user.
4. **Public `/api/status`:** aggregate only (workspaces running / starting / waiting / stopped, starts available now, CPU and memory
   reserved and used percent, idle timeout). No names, hosts or runtime identities.

## Also in this change

- **No account cap:**
  - `MAX_ACCOUNTS` raised to 100000, the default policy is unlimited, and raising the limit no longer needs a compute report;
  - `newAccountRecord` no longer checks the cap;
  - signup admission blocks only on storage (or a stale or missing controller report), not on CPU or memory.
- **Retired slots** no longer count against the inventory (active slots ≤ 200, entries ≤ 400).
- **Right-sizing:** new runtimes request 100m CPU (was 250m; measured idle use is 15–30m), keeping the 4-CPU burst limit. The pair
  CPU floor drops from 0.6 to 0.25.
- **History:** generated runtime Deployments keep `revisionHistoryLimit: 2`.

## Tests

- New: `tests/test_capacity_session.py`, `tests/test_session_demand.js`, `tests/test_first_come_gateway.js`.
- Updated to the new semantics: `test_capacity_planner.py`, `test_capacity_report.py`, `test_capacity_policy.js`,
  `test_admin_capacity.js`, `test_self_registration.js`, `test_signup_capacity.js`.

## Not done yet

1. **Idle warning:** a notice about 5 min before an idle stop, injected into the workspace UI.
2. **Retention:** delete a retired account's runtimes, Services and PVCs after a 30-day grace period. This needs a separately reviewed
   delete permission, deliberately not given to the scaling controller.
3. **Housekeeping:** `ttlSecondsAfterFinished` on the remaining Job creators; a pruning job for old hash-named ConfigMaps.
4. **Admin dashboard wording:** the capacity form still shows the "maximum accounts" field. It is now informational.

## Deploying source changes

The gateway and controller run code from immutable, hash-named ConfigMaps, not from the image. `scripts/rollout_dsh_sources.py`
builds that ConfigMap from git, switches only the source volume, waits for the rollout, verifies it, and switches back automatically on
failure. For the gateway, verification checks that `/login`, `/api/status` and `/api/signup-capacity` return 200.

```bash
python3 scripts/rollout_dsh_sources.py both          # dry run: prints the files that would change
python3 scripts/rollout_dsh_sources.py both --apply  # deploy: controller, then gateway
```

- Targets: `both`, `controller` or `gateway`.
- The controller rollout also adds the two Role rules it needs (`deployments/scale` get/patch, `deployments` list). It only adds rules
  and never removes any.
- Credentials: a Kubernetes token with deploy rights in the DSH namespace, `DSH_K8S_API` (your cluster API URL) and optionally
  `DSH_K8S_CA_FILE`. TLS verification is never disabled.
- In CI, run it from a main-branch job and gate it on an explicit flag (for example a `[deploy-dsh]` marker in the commit message), so
  an ordinary commit only prints the plan.

## Rollout order

1. Roll the controller first. With no `demand.json` yet, it stops and starts nothing; it only publishes `sessions.json`.
2. Roll the gateway. It seeds demand from current sessions. After one idle period, unused workspaces stop.
3. Verify:
   - `/api/status` and the sign-in panel;
   - a sign-in to a stopped workspace shows the progress page and then reaches the workspace;
   - sign-out stops the workspace within about 20 s;
   - reserved CPU on the node drops.
4. Roll back with the previous ConfigMaps and Role. A stopped workspace can be started with
   `kubectl scale deploy/<name> -n <namespace> --replicas=1`.
