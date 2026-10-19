# Create an account and approve Internet access

## For a new user

1. Open the DSH login page and select **Create account**.
2. Choose a unique username (3–30 letters, numbers, underscores, periods or hyphens). Usernames are normalized to lowercase. Enter and confirm a password of at least 12 characters.
3. Submit **Create account**. DSH assigns an exclusive prepared runtime pair and stores the account and assignment together. Your account starts with Internet permission denied.
4. Sign in with **No Internet / Internal** selected. Your files, conversations, attachments and credentials belong to this private environment.
5. If Internet work is needed, ask an administrator for approval. After approval, logout and sign in with **Internet** selected. Its workspace and history remain separate from No Internet.

The login page shows available workspace capacity. When no unused pair remains, signup refuses the request without creating an unusable account or sharing another user's runtime. An operator replenishes capacity; retry after it is available.

## For an administrator

Open **Admin overview → User management**. Reload User management after a new signup, find the account and select **Allow Internet**. To remove the permission, select **Disable Internet**. Revocation invalidates that user's gateway sessions and closes tracked gateway connections, so a fresh Internet login is denied. It does not cancel processes already running in the private runtime.

The dashboard also supports **Create account**, **Enable**, **Disable** and **Sign out**. New names use available private-pair capacity; existing operator-reserved identities retain their explicit mappings. An administrator role is assigned by the operator, never by the signup form.

## Common questions

| Situation | Action |
|---|---|
| Create account is unavailable on a fresh installation | Operators first qualify empty private pairs and explicitly enable registration; bootstrap defaults remain off. |
| Signup reports full capacity | No account is created. Ask the operator to add new pairs; disabling an existing account does not free its slot. |
| A new account is missing from User management | Reload the page. Usage refresh is separate from reloading the account list. |
| Internet is still unavailable after approval | Logout and sign in again with Internet selected. Approval does not move files or history. |
| Internet permission was revoked | New Internet logins are denied and tracked gateway connections close. An operator must separately stop any detached work if required. |
| A gateway update ends the browser sign-in | The current tab shows a sign-in prompt and keeps its unsent draft in the page. Sign in in the new tab using the same account/environment, return and explicitly submit when ready. API requests receive JSON 401 rather than a login HTML document. |

## Why prepared private pairs

A small warm pool provides immediate signup on the existing node. Each slot is an empty, dedicated No Internet runtime and Internet runtime, with separate private storage and inference credentials. Allocating a pair does not grant Internet access. The gateway binds the username to the slot in its owner-only account record; it accepts no client-supplied runtime, role, host or permission.

The gateway has no Kubernetes management token. Operators provision and qualify the private pairs separately; signup only allocates capacity from the reviewed, read-only catalog. Hashing the password and allocating the unique slot are one synchronous account-store transaction in a single gateway writer. Its atomic file replacement preserves the assignment across gateway replacement. Use one gateway replica with Recreate handover; this file-backed allocator is not a multi-replica account database.

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
