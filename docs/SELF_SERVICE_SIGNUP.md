# Create an account and approve Internet access

Accounts prepared by the automatic capacity controller include JupyterLab in their private No Internet environment. Choose JupyterLab when signing in. The separate Internet environment needs an admin grant. Existing administrator Stop choices are preserved; signup does not approve arbitrary app commands.


## For a new user

Successful signup enables your private **No Internet / Internal** workspace immediately, without individual administrator approval. **Only Internet access requires a separate administrator grant.** Account capacity controls are not an approval queue.

1. Open the DSH login page and select **Create account**.
2. Choose a unique username (3–30 letters, numbers, underscores, periods or hyphens). Usernames are normalized to lowercase. Enter and confirm a password of at least 12 characters.
3. Submit **Create account**. DSH assigns an exclusive prepared runtime pair and stores the account and assignment together. Your account starts with Internet permission denied.
4. Sign in with **No Internet / Internal** selected. Your files, conversations, attachments and credentials belong to this private environment.
5. If Internet work is needed, ask an administrator for approval. After approval, logout and sign in with **Internet** selected. Its workspace and history remain separate from No Internet.

The login page shows **N new-user slots available**, refreshed every 15 seconds while visible and when returning to the tab. This is unused prepared account capacity, not the number of project folders or app URLs assigned to a user. A failed refresh shows capacity unavailable. When no unused pair remains, signup refuses the request without creating an unusable account or sharing another user's runtime. Automatic replenishment prepares replacement pairs up to the spare target; there is no account limit. The default target is two warm spares. Retry after preparation finishes; ask an administrator if sign-ups stay paused (local storage below the 200 GiB reserve). See the [capacity walkthrough](PLATFORM_CAPACITY_AND_CLIENTS.md).

### When the installation is full

**0 new-user slots available** is a normal full-capacity result. The capacity endpoint returns HTTP 200 with `remainingSlots: 0`; existing users can still sign in. A new signup is refused without creating an account, changing the limit or reusing another user's workspace.

Existing and disabled accounts retain their assignments. If more accounts are retained than the current ceiling, the count still stays at zero rather than reporting a capacity-service error. Reading capacity does not increase the ceiling or delete accounts. Administrator policy changes retain their validation and permission checks.

The unavailable message is reserved for a genuine capacity-data or service error, not a valid full installation.

## For an administrator

Open **Admin overview → User management**. Reload User management after a new signup, find the account and select **Allow Internet**. To remove the permission, select **Disable Internet**. Revocation invalidates that user's gateway sessions and closes tracked gateway connections, so a fresh Internet login is denied. It does not cancel processes already running in the private runtime.

The dashboard also supports **Create account**, **Enable**, **Disable** and **Sign out**. New names use available private-pair capacity; existing operator-reserved identities retain their explicit mappings. An administrator role is assigned by the operator, never by the signup form.

## Common questions

| Situation | Action |
|---|---|
| Must I wait for approval after signup? | No. Sign in to No Internet immediately. Only Internet access needs a grant. If an administrator later disables your entire account, both environments are blocked until re-enabled. |
| Create account is unavailable on a fresh installation | Operators first qualify empty private pairs and explicitly enable registration; bootstrap defaults remain off. |
| Signup reports full capacity | No account is created. Wait for automatic preparation or ask the administrator to check local storage (sign-ups pause below the 200 GiB reserve); disabling an account does not free its slot. |
| A new account is missing from User management | Reload the page. Usage refresh is separate from reloading the account list. |
| Internet is still unavailable after approval | Logout and sign in again with Internet selected. Approval does not move files or history. |
| Internet permission was revoked | New Internet logins are denied and tracked gateway connections close. An operator must separately stop any detached work if required. |
| A gateway update ends the browser sign-in | The current tab shows a sign-in prompt and keeps its unsent draft in the page. Sign in in the new tab using the same account/environment, return and explicitly submit when ready. API requests receive JSON 401 rather than a login HTML document. |

## Capacity administration

Open **Admin overview → Account capacity and automatic provisioning** to set **Warm spare slots** and **Automatic replenishment**, then select **Save capacity settings**. Lowering a target never deletes an existing workspace. See the [complete capacity guide](AUTOMATIC_ACCOUNT_CAPACITY.md).

## Why prepared private pairs

A small warm pool provides immediate signup on the existing node. Each slot is an empty, dedicated No Internet runtime and Internet runtime, with separate private storage and inference credentials. Allocating a pair does not grant Internet access. The gateway binds the username to the slot in its owner-only account record; it accepts no client-supplied runtime, role, host or permission.

The gateway has no Kubernetes management token. A separate trusted provisioner prepares and qualifies replacement pairs automatically using operator-approved templates and capacity settings; signup only allocates ready capacity from the reviewed, read-only catalog. Operators perform the one-time installation and enable registration; they do not approve each new No Internet user. Hashing the password and allocating the unique slot are one synchronous account-store transaction in a single gateway writer. Its atomic file replacement preserves the assignment across gateway replacement. Use one gateway replica with Recreate handover; this file-backed allocator is not a multi-replica account database.

No Internet workers inherit infrastructure egress restrictions and non-root execution. The gateway mounts launch tokens read-only, never workspace roots. Workers mount only their own central CIFS subpaths or private Internet volumes. Accounts do not inherit a personal AD identity, Kerberos ticket or datalake entitlement. Shared GPU inference does not merge files or histories.

Disabled accounts retain their slot, data and history. Slots are not recycled automatically, even when someone stops using the service. Reassignment requires explicit retirement, reconciliation and verified deletion of the previous private state; creating a new slot is the normal replenishment path. Test-only pairs never enter the live catalog.

## Operator setup and replenishment

Run from the repository root in a POSIX operator shell with an authenticated `kubectl`, Python/PyYAML and access to the approved private runtime templates. Keep all generated files in a private directory outside the repository. Existing site values and generated credentials must not be committed.

1. Run `node tests/test_self_registration.js`, `node tests/test_admin_users.js`, and `python -m unittest discover -s tests -p test_signup_pool.py`.
2. Prepare six **new** pairs from a reviewed ordinary private user, retaining two pairs exclusively for acceptance:

```sh
python scripts/prepare_signup_pool.py \
  --template-user "$TEMPLATE_USER" --pool-id "$NEW_POOL_ID" --count 6 \
  --output "$PRIVATE_DIR/pool" --apply
python scripts/prepare_signup_config.py \
  --pool "$PRIVATE_DIR/pool/pool.private.json" --reserve-test-pairs 2 \
  --output "$PRIVATE_DIR/config" --apply-configmap
```

For replenishment, add `--existing-live "$PREVIOUS_LIVE_POOL"` to the configuration command. Use the previously saved `live-pool.private.json`; retain every already published slot. The existing pool stays available to its assigned users while new signup is temporarily disabled for qualification. Never overwrite the original user-routing ConfigMap or replace an assigned runtime with a fresh one.

3. Record the currently mounted gateway source SHA-256, preserve the old Deployment, and stage the new gateway source and read-only token mounts with signup disabled:

```sh
python scripts/rollout_admin_management.py --apply \
  --expected-source-sha256 "$CURRENT_GATEWAY_SHA256" \
  --signup-config "$PRIVATE_DIR/config/stage-gateway.private.json" \
  --output "$PRIVATE_DIR/stage"
```

4. Wait for the new workloads and verify actual startup. Fresh runtimes initialize from the pinned image. Do not copy an old user's one-time profile-backup migration init into empty state. Then run the real signup test:

```sh
python scripts/run_signup_acceptance.py \
  --pool "$PRIVATE_DIR/pool/pool.private.json" \
  --output "$PRIVATE_DIR/acceptance"
```

This creates two synthetic accounts only in a loopback candidate store, checks real DSH histories and replies, executes terminal marker tests, denies peer histories, replaces only the reserved test runtimes and checks persistence. The candidate gateway is restarted to verify account assignment persistence. The tool retires test runtimes after acceptance; it does not allocate them to real users.

5. Verify the live candidate pool still has empty native histories, readable launch tokens, non-root execution, no management token and enforced No Internet/peer-network denial. Preserve its qualification result. Enable only with matching accepted source:

```sh
python scripts/rollout_admin_management.py --apply \
  --expected-source-sha256 "$STAGED_GATEWAY_SHA256" \
  --signup-config "$PRIVATE_DIR/config/live-gateway.private.json" \
  --signup-acceptance "$PRIVATE_DIR/acceptance/result.json" \
  --output "$PRIVATE_DIR/enable"
```

6. Open the actual login page, check the Create account tab and default No Internet choice, and confirm the admin controls and remaining capacity. Compare existing account fingerprints and workload identities with the saved baseline. Retain the old gateway specification for configuration rollback; never restore an older account-store file over newer registrations. On a regression, disable new signup and preserve all assignments and private data while investigating.

## Recorded acceptance

The 19 October 2026 candidate test created two accounts, four native histories and four private workspace/attachment marker pairs. Two actual DSH replies passed. Cross-user and cross-environment history reads were denied; default Internet access was denied. The files, histories and account assignments survived the four test-runtime replacements and candidate-gateway replacement. Admin Internet revocation denied a new Internet login while No Internet remained available. The public catalog reserves four different, empty pairs; capacity decreases as accounts sign up.


<a id="capacity-planning"></a>

## Calculate and adjust shared account capacity

Open **Admin overview → Account capacity and automatic provisioning → Shared infrastructure capacity**. The panel refreshes every 15 seconds while visible and shows its observation time. This is a current infrastructure planning calculation, separate from the model's request-concurrency limit.

**There is no account limit** since 30 Oct 2026: an account holds storage only, and new sign-ups pause only when local storage would fall below the 200 GiB reserve. The planning ceiling below is informational. Additional single-owner instances such as DSH2 and DSH3 have separate account stores. Their configured owner accounts appear in the total, and their CPU, memory and pod reservations are already deducted with every other cluster workload. They are not subtracted a second time.

CPU and RAM start from node allocatable capacity minus the larger of current measured usage and Kubernetes reservations. Metrics older than 90 seconds or unavailable measurements pause preparation and prevent a complete recommendation. The resource table shows available capacity before the protected reserve, that reserve, the budget for one new private No Internet + Internet pair, and how many additional pairs each resource supports. Future pair budgets are derived from the generated worker templates, sidecars and private storage claims, with conservative minimums of 0.6 CPU cores, 2.25 GiB RAM, 23 GiB local storage and two pods. Larger templates increase the budget automatically. Unscheduled pending pods also consume the planning budget. Node allocatable values already exclude Kubernetes-reserved resources; the controller keeps an additional installation reserve (default 2 cores, 32 GiB RAM, 32 GiB local storage and 10 pod slots).

For each resource:

```text
additional pairs = floor(max(0, available - protected reserve) / new-pair budget)
new pairs possible = minimum across CPU, RAM, pod slots, storage and remaining inventory entries
main planning ceiling = min(32, registered main accounts + existing ready pairs + new pairs possible)
total planning ceiling = main planning ceiling + configured additional-instance owner accounts
```

Ready pairs have already consumed their reservations, so they are counted once. Retired slots are never reused and still consume an inventory entry. For example, 12 main accounts, two ready pairs and room for five additional pairs produce a main planning ceiling of 19. Two additional owner-only instances make the total planning ceiling 21. This example is not a fixed deployment recommendation: the dashboard recalculates from current reservations and CSI storage capacity.

Central file-share free space is displayed separately. It is shared storage, not a guaranteed per-user quota. Data growth, backups, network performance and peak application demand need their own operating budgets. This calculation does not establish how many users can simultaneously saturate CPU limits, run notebooks or issue near-1M requests. All accounts share the inference service and its independent admission controls.

To change settings:

1. Check the fresh calculation and any additional-instance readiness. An unknown or stale value is unavailable, never zero.
2. Set **Warm spare slots** (0–8) and automatic replenishment on/off. There is no account-limit field.
3. Save and refresh, then check the provisioner observation. A stale or incomplete observation pauses preparation while preserving existing users and the saved policy.
4. A lower spare target or paused replenishment does not delete accounts, recycle old workspaces, stop running users or change their permissions. Prepared slots and account admission remain separate from Internet approval and application-name quotas.

Operators must declare every additional fixed-owner deployment in the controller's private site configuration (`additionalAccountDeployments`). During installation, repeat `--additional-account-deployment NAME=LABEL` for each additional instance. The controller checks the actual deployment and its fixed `AUTH_USER` identity. If any declared instance is missing or ambiguous, no complete recommendation is published and limit increases are refused. The public setup supports an explicit empty list for installations without additional instances. Never place credentials in this configuration.


### Automatic signup pause and recovery

Signup checks the trusted capacity snapshot on every new-account attempt, including administrator-created accounts and already-prepared warm spares. If CPU, RAM, pod slots or local storage cannot retain the protected reserve **plus one private-pair budget**, new signup pauses. The login page reports **0 new-user slots available** and the registration request returns **503**, without creating an account. The dashboard shows the admission state and reason. The pair budget is an extra safety cushion; it does not count a prepared pair twice in the planning ceiling.

The collector includes every workload on the node, including agents, Jupyter kernels, user apps and the configured DSH2/DSH3 instances. CPU/RAM use the larger of observed consumption and reservations. Signup also pauses if the collector report is one minute old, its underlying node usage is 90 seconds old, measurements are missing/malformed, the main account count has not yet reconciled, or additional-instance coverage is incomplete. Missing information never opens signup.

Admission is evaluated again on each request. A fresh complete healthy report automatically reopens remaining warm spares, within the unchanged account limit; the controller normally refreshes every 15 seconds. No restart or administrator action is needed. A recently created account may briefly pause further signup until its assignment count is reflected in the next report. Existing users can still sign in and use their assigned environments; no user, running app, data, history or configured limit is removed or changed. This is sampled admission protection, not a guarantee against instantaneous resource spikes or a GPU inference-concurrency limit.

DSH2 and DSH3 remain fixed-owner instances with self-registration disabled. Their resource consumption contributes to the shared signup gate; they do not gain a new signup route. An additional-instance measurement failure closes new main signup without changing their owner access.
