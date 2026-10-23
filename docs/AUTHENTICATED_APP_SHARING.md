# Share an application without sharing a workspace

The owner chooses who can open each ordinary application. New authenticated applications default to **All authenticated users (local and AD / LDAP)**. Existing saved applications keep their current audiences until their owner saves an edit. Sharing an app does not grant Internet access or access to the owner's workspace.

## Choose an audience

- **All authenticated users (local and AD / LDAP):** every enabled DSH account, including accounts authenticated through the configured directory. This is the default for a new ordinary application.
- **All local DSH users:** enabled locally created DSH accounts only.
- **All AD / LDAP users:** enabled accounts authenticated through the configured directory only. This does not enable directory signup or bypass its existing approval rules.
- **Selected local DSH users:** tick one or more enabled local accounts in the checkbox list. The owner always retains access and is not listed as a recipient.
- **Owner only:** keep the application private.

The server checks the stored account type after authentication and again when routing requests. Selecting a different sign-in provider cannot change an account's type. Disabled accounts are denied. The checkbox directory contains local usernames only; it does not expose passwords, directory credentials, private histories or runtime addresses.

## Create or edit an application

1. Sign into the environment running your application. Start the application on its ordinary web port, such as 8501 or 8000.
2. Open **My applications**. Enter an available name, choose **Local application port** and enter the real port. The initial notebook port 8888 keeps sharing disabled until an ordinary app port is entered.
3. Leave **Visitor access** as **Require DSH sign-in**. Choose an audience; for **Selected local DSH users**, tick the recipients. Public links have no authenticated audience and are a separate explicit choice.
4. Select **Save URL**. The approved application hostname must already have DNS, TLS and gateway routing. Saving a URL does not start the application.
5. For an existing app, select **Edit sharing / URL**. Its current settings and local recipients load into the form. The name is locked while editing. Nothing changes until **Save URL** is selected. **New application / cancel edit** resets the form without changing the saved mapping.
6. To revoke access, untick recipients and save, choose a narrower audience, choose **Owner only**, disable the mapping or remove it.

Old selected-account lists remain compatible. If all saved recipients are enabled local users, editing presents them as local checkboxes. A legacy list containing AD or unavailable recipients remains stored until an explicit audience choice replaces it. Enabled AD recipients can be retained with the legacy audience. If a recipient is unavailable, choose a new valid audience before saving a change; the server rejects unavailable recipients. Existing audiences are not migrated on page load or deployment.

## Keep user environments private

JupyterLab (8888), terminal (7681), Harness, gateway and inference management ports remain owner-only. The page disables their audience selector and the server rejects direct attempts to share them. A malformed saved mapping fails closed.

Shared requests go only to the saved ordinary app port in the owner's saved environment. A shared alias has one target in one environment. Visitors cannot choose another runtime or port using request parameters. Their normal DSH workspace, history, files, notebook and terminal still resolve to their own private runtime. A path such as `/admin` on the shared app belongs to that app; it never opens DSH administration.

DSH credentials, session cookies and caller-supplied identity headers are removed before forwarding. Application cookies remain separate. The proxy blocks attempts to set DSH or parent-domain cookies, foreign browser Origins and ambiguous encoded paths. Sharing exposes the application's own features, including any writes it offers; owners must not disguise a shell, file browser or management proxy as an ordinary application.

## Revoke access

Sign-in, HTTP and WebSocket routing enforce the saved audience, enabled accounts and owner target. Saved audience changes invalidate outstanding app-login challenges. Removing recipients or changing their eligibility closes active shared connections on the next authorization check, normally within two seconds. Logout and session expiry also end access. Switching from a group to selected users replaces the audience; it does not add exceptions to the previous group.

## Verification and rollout status

The checkbox and audience update is deployed on Main DSH. The exact source passed 158 tests in the deployed runtime image, including actual HTTP/WebSocket isolation and revocation with synthetic local and directory identities. Existing accounts, saved app audiences and browser sessions were preserved; worker identities, original history files and notebook processes were compared before and after the gateway-only update. Legacy DSH2/DSH3 entrypoints remain owner-only. These tests do not claim a fresh production AD-directory connection test.

Tests execute the actual gateway with synthetic local and AD identities, separate owner/visitor applications, and real HTTP/WebSocket connections. They verify provider-specific sign-in, owner-bound routing, denied private/management access, saved-list editing, rejection of AD recipients in local selections and closure after revocation. The returned form script is executed to verify checkbox selection, existing-setting prefill, explicit save, new-app defaults and legacy-list preservation. These checks do not modify production accounts, apps or history.

Run the app-proxy regression tests and `tests/test_ldap_gateway.cjs` before rollout. Then qualify the exact source in the deployed runtime image, retain the previous source for rollback and verify live form content, saved accounts, mappings, sessions and worker identities before claiming deployment.


[Watch the sharing walkthrough](AUTHENTICATED_APP_SHARING_WALKTHROUGH.html). This captioned illustration explains the controls; it is not a production recording.
