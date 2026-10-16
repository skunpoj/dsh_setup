# Admin dashboard

Open `https://dsh.aiportal.bot.or.th/admin` after logging in as the existing admin account. An Admin overview link appears beside Logout only for authorized administrators. The summary API is `GET /api/admin/summary`; no user-management or workload-changing actions are provided.

## Authorization and containment

`DSH_ADMIN_USERS` is an operator-controlled comma-separated allowlist, defaulting to `admin`. It does not create accounts. Identity comes from the authenticated gateway session; request headers, query parameters and login form fields cannot grant the role. Ordinary users receive HTTP 403 on both routes. Anonymous visitors receive the login page without summary content. Authenticated non-GET requests receive 405. Logout revokes the browser session.

Responses use no-store, nosniff, frame denial and no-referrer headers. The API projects an explicit set of summary fields rather than returning raw configuration. The browser renders snapshot values using textContent, not HTML insertion. It does not display passwords, cookies, account names, conversation contents or source records. The gateway retains no mounted Kubernetes API identity; it does not need cluster-wide monitoring permissions for this dashboard.

## What Refresh means

Current gateway values: registered-account count, active browser-login counts split between No Internet and Internet, routing mode and registration setting. Browser sessions are not unique users, active DSH tasks or GPU requests. Counts reset when the in-memory gateway session store resets.

Recorded snapshot: environment readiness at observation, storage and direct-network test results, backend/product token limits, request ceiling, performance samples and remaining security gaps. The page displays the infrastructure observation timestamp. The snapshot combines the configuration observation with separately recorded performance samples in the evidence files; it is not continuous health monitoring or an SLA. Refreshing the page does not run Kubernetes, network or inference tests. Missing snapshot data is shown as unknown, without fabricated healthy defaults.

Current gateway source is the audit-enabled immutable overlay `dsh-gateway-source-b34ee162ec9b`. Build 62743 is deployed. The refreshed private-user snapshot is mounted at `/admin-status/summary.json`; its exact immutable name is recorded in `context-evidence/admin-private-snapshot-live-20261016.json`. `k8s/dsh-gateway-identity-overlay.yaml` records both references. Preserve that overlay when applying base manifests until a replacement image includes this source.

## Updating and rolling back

Update `docs/context-evidence/admin-dashboard-snapshot-20261016.json` from reviewed live-status and performance evidence. Keep timestamps and unresolved controls accurate; do not add credentials, raw configuration, private filenames or conversation content. Run the admin browser/authentication test with `DSH_TEST_EVIDENCE_OUTPUT` pointing to a new evidence JSON. It records the exact source hash after successful checks.

For a snapshot-only update, use `scripts/update_admin_snapshot.py --snapshot <reviewed-json> --output <fresh-rollback-directory>`. It preserves private routing, audit mounts, source and image, replaces only the snapshot reference, verifies mounted content and actual private-user/admin behavior, and restores the previous specification on regression. The earlier identity rollout helper was designed for initial shared-pool cutover and must not be blindly reused against private routing.

On failure the script restores the complete prior Deployment specification and checks readiness. Earlier deployments retain their original dated evidence; the current snapshot-only update has its own acceptance and rollback record. The exact rollback specification is retained in `C:\Users\skunpojt\outputs\dsh-admin-rollout-20261016\gateway-before.json`. Replacing the gateway can disconnect browser connections and require login again; execution pools, histories and inference are not restarted.

## Verification and limits

Local real-HTTP and Edge browser checks passed: anonymous denial, ordinary-user denial despite forged admin headers, authorized access, no-store/read-only behavior, explicit secret-field projection, admin-only navigation, timestamp rendering, inert HTML payload, missing-snapshot handling and logout. The browser screenshot is a local synthetic fixture, not Production evidence.

Production checks passed: actual admin page/API, mounted snapshot readback, four environment rows, correct 128K user budget, ordinary-user and forged-role denial, anonymous denial and admin-only navigation. Fresh login/logout, history lists and terminal pages also passed in both environments. All 80 legacy histories in 82 files retained their aggregate hash. Temporary probe credentials were removed; other accounts were unchanged.

The first full unit-suite run hit a Windows Access Denied error while replacing a temporary file in an unrelated reconciliation test. That isolated test and the subsequent full 21-test run passed. No storage-reconciliation code was changed or executed against Production by those mocked tests.

Private-user isolation is now deployed for eight non-admin identities in both environments; all 80 histories belong to admin. The dashboard does not establish actual Kerberos/Livy/Spark identity, read-only Hive/HDFS authorization, remote worker egress, legacy-instance hardening or near-1M fairness. DA_WORKSPACE is storage, not RDT authorization. Central audit fields are time/event/user/environment and are admin-only; no passwords, tickets or conversation text are recorded. At retention capacity, new runtime/login access fails closed until operator archival.

Evidence: [local authorization/browser checks](context-evidence/admin-dashboard-tests-20261016.json), [deployed acceptance](context-evidence/admin-dashboard-live-20261016.json), [mounted snapshot](context-evidence/admin-dashboard-snapshot-20261016.json).
