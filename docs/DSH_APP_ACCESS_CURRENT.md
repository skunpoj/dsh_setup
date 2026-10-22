# DSH application aliases and sign-in

Normal DSH now provides the application destination and visitor-access controls at [https://dsh.aiportal.bot.or.th/applications](https://dsh.aiportal.bot.or.th/applications). Owners configure mappings there; visitors open the application alias directly. A separate proxy-test sign-in portal is not a required user step.

## Actual examples

| Application | AI Portal URL | Destination | DSH access and verified scope |
| --- | --- | --- | --- |
| Suprisk — registered on normal DSH | https://suprisk.aiportal.bot.or.th/ | https://suprisk.test.apps.mlops.bot.or.th/ | **Public access** at DSH. The alias returns the real MLOps SSO redirect; Suprisk's own authentication remains required. |
| RegChat — registered on normal DSH | https://regchat.aiportal.bot.or.th/ | https://regchat.dev.apps.mlops.bot.or.th/ | **Require DSH sign-in**. The existing admin/Internal session opened the actual RegChat interface through the alias. |
| Public external data — existing Test example | https://proxy-test-app4.aiportal.bot.or.th/us-states.json | https://storage.googleapis.com/cloud-samples-data/bigquery/us-states/us-states.json | No DSH or application login. Fresh verification returned 50 JSON Lines records, byte-identical to Google's source. |

The two MLOps mappings are active on normal DSH. The public-data example remains on the existing Test bridge. Normal DSH's current upstream policy permits the two approved MLOps origins; the external-URL selector does not grant access to every public or internal destination automatically. General public HTTPS forwarding has been qualified in Test, not enabled by this Main MLOps rollout.

## Owner settings

| Control | Purpose |
| --- | --- |
| Name | Registers `NAME.aiportal.bot.or.th`. |
| Target | Chooses a local application port or an approved HTTPS destination. |
| Visitor access | Chooses Require DSH sign-in or Public access for this mapping. |
| Check name / Save URL | Checks hostname availability and saves the mapping. |

The default application-name limit is eight per user, with an administrator-editable numeric limit. Registering a URL does not start an application or grant Internet access. Private destinations require approved routing, valid TLS and the configured address restrictions.

## Two visitor-access choices

**Require DSH sign-in:** DSH checks its session and the visitor's permission for the registered app and environment. When sign-in is needed, the normal DSH issuer presents an app-focused form without workspace, terminal, Jupyter or platform setup choices. Successful authentication returns to the registered application alias.

The currently implemented gated policy is bound to the mapping owner and environment, rather than every enabled DSH account. The RegChat example is owned by `admin` in the Internal environment. Another account or environment does not acquire access just because its DSH password is valid.

**Public access:** the gateway skips its DSH visitor sign-in gate for that app mapping. The destination can still require its own authentication. Suprisk uses this option while retaining its MLOps login. Public access does not expose DSH management pages or remove network-access requirements.

## Reverse proxy and browser address

```text
Browser → Application alias → DSH gateway → Approved destination
        ← Application response returned through DSH
```

A reverse proxy forwards requests on the server and returns the responses, keeping the alias for proxied requests. A redirect tells the browser to navigate to another URL, changing its address. A webhook triggers an action; it does not transport the application's ongoing traffic.

Application-generated absolute links and SSO redirects can leave the alias. In the actual Suprisk flow, the upstream redirects to `https://test.apps.mlops.bot.or.th/login` with the original Suprisk MLOps URL as `next`. The address therefore leaves the alias during SSO and may return to the original MLOps address. Keeping the alias throughout SSO requires a separately qualified application/identity-provider integration; it is not achieved by blindly rewriting authentication callbacks.

RegChat's narrowly scoped adapter changes only its top-level Gradio configuration root to the registered alias. Actual upstream HTML, configuration and JavaScript were verified; every other configuration field matched the original response. The real browser loaded RegChat on the alias with 66 components and 17 dependencies. This does not establish that a business question or every application workflow has been tested.

## Separate sessions and authentication limitations

DSH authentication and destination authentication are separate. DSH does not forward its password or session cookie to the application. The destination manages its own login and session, and logging into DSH does not automatically log into that application.

The present proxy strips incoming `Authorization` headers, including Bearer and Basic credentials. An application depending on those headers needs a separately qualified integration. Do not put credentials in destination URLs or assume platform credentials should be forwarded. External SSO also needs registered callbacks and an application-specific trust design.

## Verification boundary

The deployed Main source matches the qualified candidate runtime modules from commit `bd168a2`, with the existing runtime image unchanged. Existing account, settings, session and route bytes and the manual/course roots and manifests were preserved during activation. The current application manager shows two registered names out of eight.

Native fresh sign-in, incorrect-password rejection, separate destination login, DSH logout and Public access were verified against the isolated Test issuer using synthetic accounts. On normal DSH, the existing authorized admin/Internal browser session was preserved and opened the actual RegChat interface. Independent anonymous checks verified RegChat's normal DSH app-focused gate and API refusal, and Suprisk's own MLOps SSO redirect. No real Main session was logged out merely to run a test.

Authenticated Suprisk business use and RegChat model inference were not tested. Existing Test infrastructure has not yet been retired. Manuals, PowerPoint and English video publication have separate acceptance records; deployment of the proxy does not establish that every published format has already been updated. No historical resend was performed by this work.
