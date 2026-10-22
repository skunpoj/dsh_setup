# DSH application URLs and sign-in

An application visitor opens the application's URL directly. A separate proxy-test portal is not a required user step.

## Two access choices

| Owner's setting | Visitor experience |
| --- | --- |
| Require DSH sign-in | DSH checks the visitor's account before forwarding application traffic. The currently verified Test policy permits the mapping owner in the configured environment. |
| Public access | DSH forwards traffic without its visitor login gate. The application can still require its own authentication. |

Owners configure mappings; visitors use app links. Public access does not expose the DSH application manager or platform administration.

## Real applications and selected access settings

These are the user's selected final mappings, not a claim that normal DSH has activated them.

| Application alias | Actual destination | Selected DSH setting |
| --- | --- | --- |
| https://suprisk.aiportal.bot.or.th/ | https://suprisk.test.apps.mlops.bot.or.th/ | **Public access** at DSH; retain Suprisk's own MLOps authentication. |
| https://regchat.aiportal.bot.or.th/ | https://regchat.dev.apps.mlops.bot.or.th/ | **Require DSH sign-in**, demonstrating the DSH gate. |

Owners will use https://dsh.aiportal.bot.or.th/applications once the candidate controls are activated there. The current normal settings page remains port-only. The initial alias responses were generic DSH login pages, not proof that either requested mapping was active.

Public access bypasses only DSH authentication. It does not disable application authentication or expose DSH management pages. The currently qualified gated-app authorization policy is bound to the mapping owner and configured environment; it does not automatically grant every DSH account access.

The actual Suprisk upstream redirects to `https://test.apps.mlops.bot.or.th/login` with its original URL as `next`. Its own SSO remains intact, and the browser may leave the alias during that login flow. A reverse proxy alone does not establish SSO trust or guarantee the alias remains visible after SSO.

## Routing

A reverse proxy connects to the local port, approved internal destination or permitted external HTTPS destination on the server side. The browser keeps the app alias for proxied requests. A redirect instructs the browser to open another URL, so its address changes. A webhook triggers an action; it does not transport ongoing application traffic.

DSH must handle pages, assets, APIs, cookies, redirects and WebSockets. The upstream application may still navigate to another hostname, especially during external SSO. Each application needs its own compatibility check.

## App-focused normal sign-in

The implemented app-focused flow sends signed-out app visitors to the normal DSH issuer with a registered app context. It shows only the app's sign-in form and returns to that app after successful ordinary DSH authentication. It does not show workspace, terminal, Jupyter or platform setup choices. Existing platform users retain those options through the ordinary platform login.

The intended normal deployment uses the existing issuer and account store. The isolated Test deployment deliberately uses synthetic accounts and its own store, without copying Main credentials or sessions. A five-minute, one-use browser challenge binds the submitted form to the current registered app, owner and environment. No arbitrary return URL is accepted.

After the DSH gate, the destination application's session is separate. DSH login does not automatically sign the visitor into that application. Bearer/Basic credentials are not forwarded by the current proxy. Application SSO would require a separately designed integration.

## Current verification and remaining acceptance

On 22 October, strict TLS and hostname validation passed for both real MLOps destinations using an existing trusted BOT root and the approved private address. Suprisk returned its actual SSO redirect. RegChat returned its Gradio interface and JavaScript asset. These were read-only checks: no business question or model inference was submitted, and Suprisk's authenticated business workflow was not completed.

The current normal DSH deployment has not been replaced by this work. Activation and retirement of the old proxy-test infrastructure await coordinated cleanup, a fresh baseline and acceptance of the replacement. The isolated Test issuer is a qualification tool, not a separate portal that application users must visit.

### App form compatibility correction

A fresh native browser submission reached the Test backend and returned HTTP 403. Sanitized diagnostics showed matching Host and a valid challenge shape, but a failed Origin check. The app form page's `Referrer-Policy: no-referrer` causes a native POST to send a null Origin. The narrow candidate correction uses `same-origin` for that app-focused page; strict rejection of null, absent and foreign Origins remains in place. Sixteen local checks and three asynchronous race checks passed. Native browser verification after deploying the correction remains pending.

This supersedes the earlier explanation that browser controls could not submit the form. The original refusal and earlier evidence are preserved.

### RegChat frontend compatibility

RegChat's actual Gradio configuration embeds its MLOps URL as `config.root`. Serving initial HTML and assets through an alias does not establish that its frontend API requests stay on that alias. A narrowly scoped candidate correction now changes only that top-level root. Against the real upstream through a local candidate proxy, HTML, the JavaScript asset and `/config` passed; every other configuration field matched the direct upstream response. This is not acceptance of the deployed alias: the integrated Linux qualification, normal-gateway activation and native browser/API checks remain required.

### Publication boundary

This source guide records the selected real application settings and current evidence. HTML, PowerPoint, English video and served Test publication must each be checked against the accepted implementation before being marked current. Updating the guide does not deploy a feature, change SMP Production or resend historical records. Existing media and historical evidence remain preserved.
