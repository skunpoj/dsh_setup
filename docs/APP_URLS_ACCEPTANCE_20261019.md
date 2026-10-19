# Application routing acceptance — 19 October 2026

The main gateway provides a DSH, Web Terminal or JupyterLab login choice and private application names mapped to user-selected ports. Both canonical path URLs and operator-configured wildcard hostnames are supported. JupyterLab runs on demand; start it from the terminal with `jupyter lab`.

## Corrections deployed

- App-hostname login and platform navigation return to the canonical DSH address.
- The My applications form enables Check and Save only after authenticated settings load.
- Hostname reservations include NGINX server aliases as well as Ingress rules.
- App mapping save/delete events appear in the administrator's recent access audit.
- Setup instructions explain wildcard routing, TLS, DNS, shared cookie scope and configurable public deployment domains.

## Verification

| Check | Result |
|---|---|
| Source regression suite | Owned HTTP/WebSocket forwarding, wrong-user and wrong-environment denial, CSRF, port restrictions, hostname collisions, stale inventory and mapping persistence passed |
| Disposable users | Two accounts, four private runtimes, four native sessions and two exact DSH replies passed |
| Isolation | Four cross-user and four cross-environment history requests denied; default Internet denial and admin revocation passed |
| Persistence | Four terminal writes read back after replacing all four disposable runtimes; account assignments survived gateway process replacement |
| Browser | Three login choices, form loading protection, name check/save and an actual JupyterLab page passed |
| Live gateway | Running source matched the reviewed source; custom-host login, app management and terminal navigation redirected correctly over verified TLS |
| Documentation | 24 saved HTML pages passed 72 viewport checks; the 22-file published bundle passed hash verification |
| Cleanup | Disposable gateway removed and four disposable runtimes stopped; their test storage retained |

Existing account content was preserved by the guarded gateway handover. The saved gateway specification remains available for rollback. No inference configuration change or production worker restart was requested.

Read [Application URLs and Ingress setup](APP_URLS_AND_INGRESS.md) for operating and installation steps, and [the user manual](DSH_USER_MANUAL.md) for normal usage.
