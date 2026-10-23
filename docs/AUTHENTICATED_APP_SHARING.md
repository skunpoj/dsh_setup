# Share an application without sharing a workspace

An owner can explicitly share an ordinary local web application with selected enabled, signed-in DSH accounts, or explicitly with all enabled accounts. Existing private applications stay owner-only until the owner saves that choice. Previously shared audiences are preserved. Sharing does not make an application public or grant Internet access.

## Owner workflow

1. Sign into the environment that runs the application and start the application on its ordinary web port, for example 8501 or 8000.
2. Open **My applications**, choose an available name and **Local application port**, then enter the application's actual **Port** (for example 8501). The default notebook port 8888 keeps sharing disabled.
3. Leave **Visitor access** set to **Require DSH sign-in**. Under **Authenticated visitors**, choose **Selected authenticated users** and enter the existing DSH usernames separated by commas. Choose **Any enabled DSH account — shared application** only when that wider audience is intended.
4. Save the URL and give visitors the approved application hostname. DNS, TLS and the application-host route must already be configured. Cross-user sharing uses that hostname, not another user's `/proxy/PORT` route.
5. To stop sharing, save **Owner only**, disable the mapping through administrator controls, or remove it.

Use a separate alias with one target and one environment. A shared local alias cannot also contain an external target or another environment's port. The application remains in its owner's selected runtime even when a visitor normally uses a different environment.

## What stays private

JupyterLab (8888), the web terminal (7681), gateway, Harness and inference management ports cannot use authenticated sharing. These choices remain owner-only, and the API rejects attempts to bypass the disabled selector. A malformed saved mapping also fails closed at request time.

The shared hostname forwards requests only to the saved application port in the owner's runtime. It does not expose DSH's account administration, chat history, attachments, file service, terminal, notebook or other ports. Paths such as `/admin` on that hostname belong to the selected application; they never dispatch to DSH administration. A visitor's normal DSH workspace routes remain bound to the visitor's own runtime.

DSH session cookies, bearer credentials and caller-supplied DSH identity headers are removed before forwarding. Application cookies are separate; an application cannot set DSH authentication cookies or parent-domain cookies through this proxy. Foreign browser Origins and ambiguous encoded paths are refused. Shared responses use `Cache-Control: no-store`.

## Revocation and application responsibilities

The gateway checks that both owner and visitor accounts are enabled and that the saved target is still authorized. HTTP streams and WebSocket connections are monitored for mapping, account and session changes; revocation closes them on the next check, normally within two seconds. Logout and session expiry also end access.

Sharing grants access to the application's own behavior, including any write actions it exposes. It does not make an unsafe application read-only. The owner must not publish a file browser, shell, notebook, proxy to a management service, or sensitive report through an ordinary app port. The gateway cannot identify every service moved or proxied to an arbitrary port; protected built-in ports and owner-bound routing do not replace application authorization.

## Verification

The regression suite runs the actual gateway with synthetic users and separate owner/visitor servers. It checks saved opt-in settings, exact upstream content, owner-bound routing, private-alias refusal, management-port refusal through HTTP/API/WebSocket, app-focused sign-in without a workspace, credential/cookie stripping, Origin/path rejection and revocation of active HTTP/WebSocket streams. It also executes the selector script from the returned HTML to check ordinary and protected ports.

Run `node --test tests/app_proxy/test_shared_local.cjs` and the existing app sign-in, alias recovery and public-login tests before rollout. Use an isolated canary with no production storage or credentials, retain the prior gateway source, and compare existing accounts, mappings, sessions and worker identities after rollout. Local integration tests and a canary do not by themselves prove a production deployment.

## Selected authenticated users

**Selected authenticated users** is deployed on the Main DSH gateway alongside Owner only and Any enabled DSH account. The gateway rollout preserves private execution and storage; DSH2/DSH3 legacy entrypoints remain owner-only.

Choose Selected authenticated users and enter existing DSH usernames separated by commas. The gateway accepts 1–128 distinct enabled accounts, stores the normalized list with that application and always retains owner access. Unknown, disabled, duplicate and malformed accounts are rejected. No account directory, password or private runtime information is exposed to visitors.

The list grants access only to that application's hostname, target and selected environment. It does not grant Internet permission or access to the owner's workspace, histories, JupyterLab or terminal. JupyterLab and terminal ports remain owner-only, even when a request bypasses the page and calls the save API directly.

The gateway enforces the list for sign-in, HTTP and WebSocket requests. Removing a recipient invalidates pending app login challenges and closes existing app connections on the next authorization check (normally within two seconds). Disabled users remain denied even while their names are saved. Owners can update the same alias to replace the recipient list; choosing Owner only or Any enabled DSH account clears the saved list. Existing mappings are not migrated automatically.

Local integration tests verified actual upstream content for allowed users, refused another authenticated user, rejected management-port sharing, persisted the list, rejected disabled recipients and closed active HTTP and WebSocket connections after recipient removal. The exact deployed source/image was also qualified in an isolated runtime. Live gateway source, rendered selector and preservation checks are recorded separately; no existing app audience was changed by deployment.
