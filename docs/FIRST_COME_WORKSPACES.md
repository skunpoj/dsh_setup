# First-come, first-reserved workspaces

Status: implemented on branch `feat/dsh-first-come-reserve-20261030`. **Not deployed.**

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

## Not done yet (next steps)

1. **Idle warning:** a notice about 5 min before an idle stop, injected into the workspace UI.
2. **Retention:** delete a retired account's runtimes, Services and PVCs after a 30-day grace period. This needs a separately reviewed
   delete permission, deliberately not given to the scaling controller.
3. **Housekeeping:** `ttlSecondsAfterFinished` on the remaining Job creators listed in the design review; a pruning job for old
   hash-named ConfigMaps.
4. **Admin dashboard wording:** done 30 Oct (1955613). The form has no account-limit field and states that there is no account limit.
5. **Source parity (from the parity session):**
   - The live `auth_proxy.js` carries a "platform theme" overlay (4 prepended lines and two function renames, with
     `platform_ui.js`). **This branch now includes that overlay**, applied from the parity session's diff, so its `auth_proxy.js` equals
     the live file plus only this feature's edits.
   - The same scripts exist in GitHub `dsh_setup` main (blob-identical), so this change must land in both repos.
   - The controller's site `templates.json` pins old runtime images (`4e07fd6f`, `c10f792b`), so newly prepared workspaces start on
     those images.
6. **Repo default:** done 30 Oct (1955613). `maxAccounts` is dropped on read and the planner ignores it, so the live policy file's
   legacy value 32 has no effect.

## CI/CD: commit to main, deploy by flag

Same convention as the LiteLLM repository: build and push to Harbor on main, with deployment gated by a flag in the commit message.

- **Stage `Build`** (unchanged): build, test and push `da-gpu-server/dsh-runtime` to Harbor (`internal.example.invalid`).
- **New stage `DeployDshSources`** (main only, environment `dsh-production`):
  - It runs `scripts/rollout_dsh_sources.py`.
  - The gateway and controller run code from immutable, hash-named ConfigMaps, not from the image. The script builds that ConfigMap
    from git, switches only the source volume, waits for the rollout, verifies it, and switches back automatically on failure.
  - For the gateway, verification checks that `/login`, `/api/status` and `/api/signup-capacity` return 200 on the public URL.
- **Commit-message flags:**

  | Flag | Effect |
  |---|---|
  | `[deploy-dsh]` | Controller, then gateway |
  | `[deploy-dsh-controller]` | Controller only |
  | `[deploy-dsh-gateway]` | Gateway only |
  | none | Prints the plan only (the files that would change) |

  `***NO_CI***` or `[skip ci]` skips the whole pipeline.
- **The controller rollout also adds the two Role rules it needs.** It only adds rules and never removes any.
- **Pipeline variables:**
  - `K8S_TOKEN`: secret, with deploy rights in namespace `llm`;
  - optional `DSH_K8S_API` (default: the Rancher cluster proxy) and `DSH_K8S_CA_FILE`.
  - TLS verification is never disabled.
- **Approvals:** the stage is a plain job, like the LiteLLM pipeline's, and the commit flag is the gate. To also require a person to
  approve each deploy, first create and authorize an Azure DevOps environment, then switch the job to a `deployment` job. An
  environment that doesn't exist fails every main build at validation.
- **Manual equivalent:**

  ```bash
  python3 scripts/rollout_dsh_sources.py both
  ```

  This is a dry run. Add `--apply` to deploy.

## Rollout (requires approval; not performed)

1. Build the gateway and controller source ConfigMaps from this branch, using the existing hashed, immutable ConfigMap flow
   (`deploy_capacity_controller.py`). Keep the deploy-time theme overlay on `auth_proxy.js`.
2. Apply the controller Role change (`deployments/scale` get/patch, `deployments` list).
3. Roll the controller first. With no `demand.json` yet, it stops and starts nothing; it only publishes `sessions.json`.
4. Roll the gateway. It seeds demand from current sessions. After one idle period, unused workspaces stop.
5. Verify:
   - `/api/status` and the sign-in panel;
   - a sign-in to a stopped workspace shows the waiting page and then reaches the workspace;
   - sign-out stops the workspace within about 20 s;
   - reserved CPU on the node drops.
6. Roll back with the previous ConfigMaps and Role. Stopped workspaces can be started with
   `kubectl scale deploy/<name> -n llm --replicas=1`.
