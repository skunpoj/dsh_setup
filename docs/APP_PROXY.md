# Application access and HTTPS proxy setup

An application URL is a routing record, not a new workspace or process. Each local mapping stays attached to one owner and environment. Account/environment storage and execution isolation remain unchanged.

## Owner workflow

1. Sign into the intended private environment and open `/applications`.
2. Choose **Local application port** or **External HTTPS application**. Local ports refer to that owner's runtime; external URLs require operator-approved origins and network rules.
3. Choose **Require DSH sign-in** (default), or explicitly choose **Public access** for an application intended for those visitors. The destination keeps its own login and permissions.
4. Check the alias and save it. A local alias can also use `/proxy/<name>/`; an external app uses its approved alias hostname. DNS, TLS and the wildcard/exact route must already be configured by the operator.
5. Start the local application separately, or enable its approved managed startup definition. Saving a URL does not start code or approve Internet access.

The default quota is eight names per user across environments. Administrators can adjust one numeric limit while preserving existing mappings. Terminal and notebook management ports cannot be published without DSH authentication.

## Sign-in and destination boundaries

App-focused sign-in uses the normal DSH verifier, fixed owner/environment binding and a short-lived, one-use browser-bound challenge. It returns only to the registered app. It does not offer workspace, terminal, notebook or account-registration actions. Mapping changes are rechecked after asynchronous password verification. Public mappings bypass the DSH visitor gate only for that mapping; they do not bypass destination authentication or publish DSH management.

Forwarding strips DSH authentication cookies, bearer/basic authorization and proxy identity credentials. Destination session cookies remain the destination's responsibility. Approved SSO redirects may leave the alias. Destination applications retain their own models and data permissions: an app proxy does not change them to the DSH inference configuration.

## Operator setup

1. Build the runtime with the complete `scripts/` directory. `auth_proxy.js` requires the app-sign-in, external-upstream, external-DNS and Gradio adapter modules in addition to the existing password, session, capacity, signup, course and package helpers. Never replace only the entry file.
2. Provision an app-only domain, TLS and a route to the authenticated gateway. Configure `DSH_TRUSTED_HOST`, `DSH_APP_DOMAIN`, the fresh hostname inventory and protected app-registry paths. Do not expose worker ports directly.
3. Set `DSH_APP_LOGIN_ENABLED=true` to enable the focused issuer form. Keep registration and Internet approval under the existing operator policy.
4. Supply `DSH_EXTERNAL_TARGETS_FILE` as a protected policy file. The conservative default is a named HTTPS origin with explicitly approved IP addresses and, when needed, its trusted CA. Do not use a wildcard private-origin allowance. Literal-IP URLs, loopback and metadata destinations are refused.
5. If external lookups need a separate resolver, configure `DSH_EXTERNAL_DNS_SERVERS` only for proxy requests and allow that resolver/destination through the gateway's network policy. Worker DNS and No Internet egress do not change. Keep strict TLS verification; do not disable certificate checks.
6. Configure generic public HTTPS forwarding only after an explicit operator decision and corresponding egress review. Installing the proxy modules does not enable it. A browser Public mapping and permission to contact arbitrary public destinations are separate settings.
7. The Gradio adapter is disabled by default. To qualify a destination, set both `DSH_GRADIO_UPSTREAM_ORIGIN` and `DSH_GRADIO_PUBLIC_ORIGIN` to exact named HTTPS origins and select `frontendAdapter: "gradio-root"` in its protected target policy. Use it only when that destination's root configuration requires it. It changes the qualified top-level root only; it is not a general HTML, script or CSP rewrite engine.
8. Verify unauthenticated API `401` JSON, correct/wrong login, owner/environment denial, destination login, credential stripping, real WebSocket traffic, session persistence, logout revocation and source-preserving recovery. Retain the old source and current data; never restore old accounts or histories simply to revert code.

Use the provided gateway and app-proxy tests with synthetic accounts. These tests do not authenticate to a real business application or prove that its model, permissions or downstream services satisfy your deployment policy. Preserve original user data and qualify the affected deployment before promotion.

## Portable regression checks

Run from the repository root with Node.js and Python installed:

```sh
node --test tests/app_proxy/test_app_signin.cjs tests/app_proxy/test_external_dns.cjs tests/app_proxy/test_gradio_alias.cjs
node tests/app_proxy/verify_app_login_races.cjs
python tests/run_app_proxy_tls.py
python -m unittest discover -s tests -p test_render_manifests.py
python scripts/scan_public.py
```

The TLS runner generates temporary synthetic certificates and state, keeps verification enabled, and requires an owned private IPv4 interface. Linux installations use OpenSSL; Windows can use Python's `cryptography` package. No real accounts, application data or inference requests are used. The optional `--previous-source` argument qualifies source-preserving rollback against a separately supplied previous gateway directory. Source tests do not replace a built-image or live deployment acceptance check.

## Qualification scope

The portable source checks cover 30 focused sign-in/DNS/Gradio cases, three asynchronous login races, six existing authentication/routing/password/signup suites and three manifest cases. The strict-TLS forwarding fixture passed 26 cases; its optional previous-source recovery case is skipped unless a previous source directory is supplied. These checks used Node.js 24 on Windows. The accepted site deployment was qualified separately on its pinned Linux runtime. No new public application image was built by this source-only promotion.

One initial Windows logout-fixture run returned the intended storage-unavailable response instead of completing logout; an unchanged rerun passed. The cause was not established. This local observation must not be presented as a demonstrated production failure or an eliminated filesystem risk.
