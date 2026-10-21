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
| Gated internal demonstration | https://proxy-test-app5.aiportal.bot.or.th/login | Requires the existing normal DSH session, then the demonstration application's own login |
| Public internal demonstration | https://proxy-test-app6.aiportal.bot.or.th/login | Opens the demonstration application's login without a DSH gate |
| Public data through DSH | https://proxy-test-app4.aiportal.bot.or.th/us-states.json | Fifty US-state records, without a DSH login |
| Original data | https://storage.googleapis.com/cloud-samples-data/bigquery/us-states/us-states.json | Upstream source for byte comparison |

These demonstration aliases still contain Test in their names. They remain on the dedicated Test gateway. They are not evidence that the normal DSH gateway already serves the new general-domain feature.

## Routing

A reverse proxy connects to the local port, approved internal destination or permitted external HTTPS destination on the server side. The browser keeps the app alias for proxied requests. A redirect instructs the browser to open another URL, so its address changes. A webhook triggers an action; it does not transport ongoing application traffic.

DSH must handle pages, assets, APIs, cookies, redirects and WebSockets. The upstream application may still navigate to another hostname, especially during external SSO. Each application needs its own compatibility check.

## App-focused normal sign-in

The integrated candidate sends signed-out app visitors to the normal DSH issuer with a registered app context. It shows only the app's sign-in form and returns to that app after successful ordinary DSH authentication. It does not show workspace, terminal, Jupyter or platform setup choices. Existing platform users retain those options through the ordinary platform login.

The candidate does not create another authentication service or account store. A five-minute, one-use browser challenge binds the submitted form to the current registered app, owner and environment. No arbitrary return URL is accepted.

After the DSH gate, the destination application's session is separate. DSH login does not automatically sign the visitor into that application. Bearer/Basic credentials are not forwarded by the current proxy. Application SSO would require a separately designed integration.

## Current release status

At the fresh 21 October readback, the normal DSH gateway still uses the capacity/session source `9e2e8779`; the dedicated Test gateway uses normal-session validation source `0a679fce34de`. The new combined candidate passed 75 isolated Linux checks, including feature-off recovery, but is not yet live. Live browser acceptance, exact deployment review and normal-gateway promotion remain before the Test gateway can be retired.

SMP is intentionally separated: Test loads triage V4 (`e91f8d53`, prompt SHA-256 `cd860e2b3694f32a091b2b7c294c820d8cc715f6b84d40c8a639a7b6251c4274`); Production loads the original prompt (`137b80ef39`, SHA-256 `ff5ef1ff5b0ed7f966a4637325828be37bbd14e6b9ea800a779665829b39f277`). Both actual prompt loaders matched their files, both watchers were enabled with fresh heartbeats, and all six checked Core containers were ready with zero restarts. This is a runtime/source check, not a new classification-accuracy experiment.

No Production deployment or historical resend was performed for this candidate work. Existing evidence and the working Test demonstrations are preserved pending replacement. The English video/PPTX have not been regenerated for this candidate and must not be described as current coverage of it.
