# Credential page theme qualification

The credential page uses the shared website-inspired navy palette, typography, rounded panels and focus treatment. Assets are local; the page requests no external fonts or images. The change wraps the existing renderer and adds a stylesheet. Authentication, nonce, browser encryption, ownership checks, approvals and connector behavior are unchanged.

Qualification on 24 October 2026 passed in the disposable HTTPS browser environment: desktop and mobile rendering, computed palette, private reauthentication, encrypted entry, cleared secret field, cross-user isolation, disable/delete and no browser-storage retention. Source tests verify that removing the inserted stylesheet leaves the original rendered HTML and client script unchanged in both environments. No real provider credentials were used.

## Live rollout, 24 October 2026

The presentation overlay is now deployed to Main, DSH2 and DSH3. It covers the gateway login page and the native workspace wrapper, with the credential page on Main. It does not add the Main credential broker to the owner-only legacy services. The Main API-token/PAT feature remains available; its authenticated browser session and configured profile list survived gateway replacement.

The rollout preserved existing container images, environment configuration, mounts and account-file hashes. Previously present legacy session files retained their hashes across replacement, and temporary workspace markers survived and were removed. A first strict file-count check triggered rollback when startup added session files: none of the original files had changed or disappeared. Subsequent acceptance checked preservation of every original file and recorded additions separately. Durable content persists; terminal processes and in-memory application state restart with a legacy pod replacement.

Main's native workspace and Credentials page were inspected in the session-owned browser. DSH2 also passed an actual owner sign-in and native workspace inspection using the browser's existing saved login. DSH3 passed the public login-form and unauthenticated-session checks; a fresh DSH3 owner browser sign-in was not performed. Do not describe these checks as complete end-to-end verification of every historical tool/session or every application.

The external check caught a separate transport regression: the themed login exceeded the legacy Jupyter transport's 16 KiB health-read limit. Only that HTML health check now accepts up to 256 KiB. Authentication/session reads retain their 16 KiB bound. Both public legacy login routes returned the themed form, and both unauthenticated session routes returned 401 after the repair. Local tests also reject oversized health responses and cover owner, environment, CSRF, revocation, startup and WebSocket boundaries.

The native workspace retains some literal dark surface colors in addition to its color aliases. The first live workspace review exposed poor contrast that the isolated credential page had not revealed. The overlay now maps both the native aliases and the sidebar/editor surfaces. After an upstream upgrade, inspect the actual workspace, sidebar, editor and dialogs; a passing credential-page test alone is insufficient. Previously qualified published manual bodies were read back after replacement and remained unchanged.

## Reproducing the presentation overlay

`scripts/theme_gateway_source.py` preserves the existing authentication function bodies and wraps their HTML output. It refuses missing or duplicate function targets. It can prepare an immutable ConfigMap from a private source snapshot with `--source-json` and `--output-json`; it does not contact Kubernetes or overwrite an existing candidate. Keep snapshots outside Git. Compare the full current deployment template, apply only the intended source reference, preserve rollback, and verify the actual public and authenticated routes. Do not substitute an older full gateway source.

The initial credential rollout script also includes this presentation overlay. The overlay does not alter stored browser preferences, provider credentials, account roles or AD permissions. Source tests cover idempotence, original function preservation, paired native background/foreground colors and absence of external theme asset requests.

The English Fola credential lesson remains applicable: this styling change does not alter its workflow or supported connector scope. OAuth consent and Kerberos acquisition still require approved application/service configuration.

OpenShell remains a separate incomplete integration. See [runtime prerequisites and remaining gates](OPENSHELL_RUNTIME_PREREQUISITES.md). The CPU-only kernel/network preflight is not a pass of its 25 product gates.
