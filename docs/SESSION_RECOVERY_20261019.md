# Browser sign-in recovery

The `Unexpected token '<', '<!DOCTYPE ... is not valid JSON` message occurred because an unauthenticated `/api/session/prompt` request received the gateway's HTML login form with HTTP 200. Gateway sign-ins live in memory, so replacement clears them while an already-open browser tab can still display its previous conversation. Cookie expiry, logout or revocation can also invalidate a sign-in. This is independent of model context capacity and stored conversation ownership.

The corrected gateway returns HTTP 401 with JSON, `Cache-Control: no-store` and an authentication-required header for unauthenticated `/api/` routes. Ordinary browser navigation still receives the login form. No expired request is forwarded to a worker or model.

Updated authenticated pages show **Your sign-in session ended**. **Sign in again** opens the login page in a separate tab so the current page and unsent draft remain in memory. The recovery check requires the same account and environment. It does not write the draft to localStorage/sessionStorage, switch accounts automatically, reload the page or resend a prompt. After signing in, return and select **I have signed in**, then submit the draft explicitly. Tabs loaded before the update need one reload after their unsent text has been copied.

The regression test replaces its gateway between sign-in and submission, verifies JSON 401 and zero upstream requests, checks that the draft survives, refuses recovery under a different account, and accepts an explicit submission after the original identity signs in. A real browser exercises the injected control. Signup, routing, admin authorization and telemetry regression checks remain separate from this browser case.

The runtime rollout preserves account records, existing private mounts, workspaces and histories. Two new acceptance-only pairs qualify the changed gateway without consuming or recycling the published signup capacity. Only those synthetic workers are replaced for persistence checks. The shared GPU model and existing user workers are not part of the gateway rollout. Configuration rollback must retain newer account and history data.

Run the ordinary regression entrypoint with `node tests/test_environment_routing.js`. Set `DSH_BROWSER_TEST=1` and `DSH_DOC_NODE_MODULES` to a directory containing Playwright to exercise the browser case directly with `node tests/test_session_recovery.js`. On Windows, the test uses the installed Edge executable; other operators supply `DSH_EDGE_PATH`.
