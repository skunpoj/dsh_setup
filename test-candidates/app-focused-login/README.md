# Integrated DSH application sign-in candidate

Status: **candidate only; not deployed to shared Test or normal DSH**. The final Linux qualification passed 75 checks. It uses the latest running normal DSH source (`9e2e8779`) and integrates the previously qualified general-domain/Public proxy support. The normal DSH source and the dedicated Test source are intentionally not yet identical.

## Visitor flow

Visitors open the application URL directly. They do not visit a separate proxy manager.

- Gated application: existing authorized DSH session continues to the application. A signed-out visitor reaches an app-focused screen at the normal DSH issuer, without workspace, terminal, Jupyter, registration or environment options. The ordinary issuer checks the password, account, runtime entitlement, environment policy, audit storage and session storage. It then returns the browser to the registered application's root URL.
- Public application: the DSH visitor gate is bypassed. The destination may still require its own login. DSH management remains authenticated.
- Platform user: the ordinary DSH login retains the existing platform options.

The application owner restriction is unchanged. This does not grant every DSH account access to another owner's gated app. The form uses a five-minute, single-use, browser-bound challenge. The return hostname is derived from the persisted mapping; arbitrary return URLs are ignored. Removed/changed mappings, other accounts, expired forms and cross-origin submissions fail closed.

## Session boundaries

The same normal DSH password verifier and persistent session store are used. No second account database or copied password records are needed for the integrated design. The app flow avoids minting a workspace runtime cookie. DSH credentials and Authorization are stripped from upstream app requests. A destination cookie login remains separate. This is not implementation of OIDC SSO, identity-header SSO or Bearer/Basic credential forwarding.

## Qualification

See `qualification/FINAL_QUALIFICATION.log` and `qualification/FINAL_SOURCE_PINS.json` for the actual executed bytes. The 75 checks include actual candidate gateway processes, correct/incorrect synthetic passwords, persisted issuer sessions, app return, owner/environment isolation, default quota eight, external content with a source reference, destination login, Public setting persistence, credential stripping, WebSocket frames/revocation, restart persistence and feature-off recovery. Counts overlap earlier runs and must not be added together.

These are isolated Linux tests with synthetic accounts and targets. They do not establish live normal-DSH browser acceptance, adoption by both remotes, or completion of documentation/video publication.

## Recovery and cleanup

The tested feature-off recovery uses this integrated source with `DSH_APP_LOGIN_ENABLED=false`. It restores the platform login presentation while retaining external proxy support, mappings and persistent sessions. Returning to `true` restores the app-focused form. The prior normal DSH source lacks general-domain proxy support and is not the preferred recovery for new external applications.

Before any live promotion: obtain the normal DSH owner's stable window, independently review the exact source/deployment/storage diffs, verify the current session-store mounts, preserve all mappings/history, capture exact UIDs/resourceVersions/specs and old immutable source, and reconcile unknown patch outcomes without retrying blindly. Do not recreate the gateway or change parent cookie scope.

The existing proxy-test gateway, demo routes and storage must remain until their replacement is proven. After successful replacement and a retention review, remove only resources owned by that Test release using recorded UID preconditions. Do not delete historical evidence, existing normal accounts or unrelated Test work.

## Build

`build_candidate.py` constructs the reviewed runtime from pinned local source snapshots. It does not deploy. The feature flag is disabled by default. The source inputs and candidate hash are recorded in `BUILD.json`.
