# DSH application URLs and sign-in

An application visitor opens the application's URL directly. A separate proxy-test portal is not a required user step.

## Two access choices

| Owner's setting | Visitor experience |
| --- | --- |
| Require DSH sign-in | DSH checks the visitor's account before forwarding application traffic. The currently verified Test policy permits the mapping owner in the configured environment. |
| Public access | DSH forwards traffic without its visitor login gate. The application can still require its own authentication. |

Owners configure mappings; visitors use app links. Public access does not expose the DSH application manager or platform administration.

## Actual configured examples

| Example | URL | Current verified purpose |
| --- | --- | --- |
| Normal DSH | https://dsh.aiportal.bot.or.th/login | Existing normal authentication and platform login |
| Gated internal demonstration | https://app-signin-gated-test.aiportal.bot.or.th/ | Uses the isolated synthetic Test issuer, then the demonstration application's own login |
| Public internal demonstration | https://app-signin-public-test.aiportal.bot.or.th/login | Opens the demonstration application's login without a DSH gate |
| Public data through DSH | https://proxy-test-app4.aiportal.bot.or.th/us-states.json | Fifty US-state records, without a DSH login |
| Original data | https://storage.googleapis.com/cloud-samples-data/bigquery/us-states/us-states.json | Upstream source for byte comparison |

These app-focused demonstrations use a separate synthetic Test issuer. They do not require visiting a proxy manager. They do not establish that the normal live DSH gateway has been promoted to this release. The public state-data example remains on the preserved earlier Test bridge.

## Routing

A reverse proxy connects to the local port, approved internal destination or permitted external HTTPS destination on the server side. The browser keeps the app alias for proxied requests. A redirect instructs the browser to open another URL, so its address changes. A webhook triggers an action; it does not transport ongoing application traffic.

DSH must handle pages, assets, APIs, cookies, redirects and WebSockets. The upstream application may still navigate to another hostname, especially during external SSO. Each application needs its own compatibility check.

## App-focused normal sign-in

The implemented app-focused flow sends signed-out app visitors to the normal DSH issuer with a registered app context. It shows only the app's sign-in form and returns to that app after successful ordinary DSH authentication. It does not show workspace, terminal, Jupyter or platform setup choices. Existing platform users retain those options through the ordinary platform login.

The intended normal deployment uses the existing issuer and account store. The isolated Test deployment deliberately uses synthetic accounts and its own store, without copying Main credentials or sessions. A five-minute, one-use browser challenge binds the submitted form to the current registered app, owner and environment. No arbitrary return URL is accepted.

After the DSH gate, the destination application's session is separate. DSH login does not automatically sign the visitor into that application. Bearer/Basic credentials are not forwarded by the current proxy. Application SSO would require a separately designed integration.

## Current release status

The isolated Test issuer serves the reviewed source `fec53f…` / `8ba09e26…`. Eighty-two Linux checks and three additional asynchronous race cases passed. Live API tests verified returned identity/content, both access modes, destination authentication, credential stripping, WebSocket echo, logout and feature-off/on recovery with unchanged persistent state.

The browser page visibly contains only the app-focused form, but native browser submission remains pending a manual check: the tested IAB controls also failed to submit a harmless local form. This is an observed browser-control limitation, not a proven application defect. The existing normal DSH gateway and working earlier bridge were not replaced or retired by this rollout.

At the fresh 19:16 Bangkok readback, SMP Test still loads triage V4 (`e91f8d53`, SHA-256 `cd860e2b3694f32a091b2b7c294c820d8cc715f6b84d40c8a639a7b6251c4274`); Production loads the original prompt (`137b80ef39`, SHA-256 `ff5ef1ff5b0ed7f966a4637325828be37bbd14e6b9ea800a779665829b39f277`). Both actual loaders matched their files; both watchers were enabled with fresh heartbeats. This check did not run a new classification-accuracy experiment.

A separately authorized Main signup-helper hardening was preserved and was not part of this Test rollout. No Main/Production promotion or historical resend was performed by this work. The English video, PowerPoint and Test documentation site have not been republished for this new flow; they must not be described as current coverage of it. Full API/recovery and known-limit evidence is saved with the candidate.
