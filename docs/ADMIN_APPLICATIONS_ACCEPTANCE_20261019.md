# Admin application management acceptance — 19 October 2026

The main gateway now uses one simple name limit per user: default 8, with an administrator-editable numeric override. No 16/64-name approval tiers apply. A limit reduction retains existing URLs and prevents only additional names while usage is at or above the limit.

## Qualified behavior

- Central inventory lists account status, Internet approval, usage/limit, owner, alias, both environment ports, enabled state and hostname readiness.
- Real browser actions changed a disposable owner's limit from 8 to 12, edited its app port from 8000 to 8001, disabled/re-enabled the mapping, tested a zero limit and removed the mapping.
- The two app ports returned different expected content. The mapping followed the changed port while remaining bound to its original owner.
- An ordinary user could not access admin management; the administrator could not open the owner's app as its owner.
- Lowering the limit below usage retained the existing route. Invalid limits, management ports, wrong owner and CSRF/origin failures were refused.
- Disabling a mapping closed held HTTP and WebSocket connections. Owner saves could not re-enable an administrator-disabled mapping.
- Per-user policy and mapping state survived gateway process replacement in the regression harness. Malformed stores returned unavailable status instead of an empty inventory.
- Audit projections retained actor, owner, alias/environment, old/new values and requested/applied outcomes without passwords or app contents.
- Two disposable accounts, four private runtime replacements, four terminal write/readbacks, two actual DSH replies and cross-user/environment history denial checks passed on the exact candidate source.

## Documentation and video

The user manual, admin guide, application URL guide, installation steps and README explain the implemented controls. The guided tour has 11 scenes. A 14.32-second silent browser recording uses disposable accounts and real apps; playback was checked independently. All 25 saved HTML pages passed 75 viewport checks. These are bounded acceptance cases, not a load-test or performance claim.

## Operational boundary

URL controls preserve files and application processes. An owner can still use numeric port routes in their own runtime. Account revocation and process termination remain separate operations. Registry/policy storage remains single-writer and retains the existing 4,096-name safety bound. The model and production execution workers were not part of this gateway deployment.
