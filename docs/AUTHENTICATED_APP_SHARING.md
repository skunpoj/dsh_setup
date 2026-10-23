# Share an application without sharing a workspace

An owner can explicitly share an ordinary local web application with any enabled, signed-in DSH account. Existing applications stay owner-only until the owner saves that choice. Sharing does not make an application public or grant Internet access.

## Owner workflow

1. Sign into the environment that runs the application and start the application on its ordinary web port, for example 8501 or 8000.
2. Open **My applications**, choose an available name and **Local application port**.
3. Leave **Visitor access** set to **Require DSH sign-in**. Under **Authenticated visitors**, choose **Any enabled DSH account — shared application**.
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
