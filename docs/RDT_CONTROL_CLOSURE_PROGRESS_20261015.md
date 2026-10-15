# RDT pilot control closure: implementation and evidence

> Historical 18:10 ICT snapshot. The execution-pool rollout has since completed; see the [20:39 live rollout assessment](DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.md#safe-runtime-rollout--actual-deployed-result) and [recorded results](context-evidence/runtime-rollout-live-20261015.json). Other security gaps remain open.

Updated 15 October 2026, 18:10 ICT. This supplements the original 13:03 assessment; it does not replace historical observations with later source tests.

## Current decision

The three controls remain partially satisfied. Source hardening is implemented and tested, an immutable image has passed CI and cluster smoke tests, and registration hardening has been deployed to the gateway. Execution-pool image updates, per-user cutover, approved data scope and deployed cross-user/source-access negative tests are still required. No RDT access, ownership or pilot membership has been inferred from existing shared account stores.

## Changes completed in source

- Server model catalog, client catalog and client recovery catalog advertise only internal LiteLLM. External `deepseek-official` selections were removed. Generated settings continue to use the internal cluster endpoint. This is catalog hardening; network enforcement remains necessary against arbitrary generated code or edited settings.
- Public account registration defaults to disabled, independently of per-user routing. Its tab/form are absent, direct POST returns 403, and the account store remains unchanged. Explicit legacy opt-in cannot enable registration in isolated routing mode.
- Dedicated identity/environment manifests retain separate private workspace, history, attachment and launch-token volumes. The generator now supports an explicitly approved RDT snapshot PVC at `/data/rdt`, read-only at both claim and mount, only in Secure runtimes. The generator requires a paired owner approval reference. It does not create or broaden source permissions.
- Azure image verification executes catalog and gateway-routing tests and inspects installed catalogs for external-provider entries before pushing the candidate image.

## Verification performed

| Test | Result | Evidence limit |
|---|---|---|
| Executed configurator against isolated package fixtures, then evaluated emitted server/client catalogs | Only `litellm-cluster`; DeepSeek default retained | Local emitted-content test, not live catalog |
| HTTP gateway registration denial | Form/tab absent, POST 403, no account created | Local running gateway |
| User routing, spoof resistance, missing-runtime denial and session stickiness | Passed | Local gateway with test backends |
| Generated manifest tests | Three tests passed: unique private claims/routes; invalid provisioning rejection; approved snapshot Secure-only/read-only | Manifest inspection, not actual source-write denial |
| Live runtime readback | Shared Secure and Internet pools still use digest `0505beb62188a32a63366735cead3a2e87c11e4963f6a10f6ec957b758345cbc`; gateway uses `53c9f8222d48084175bb8e18abcfb8b953eea646539880bd3643b639572f1129` | Existing deployment, not new source |
| Live policy and container specification | Offline allows cluster DNS and LiteLLM port 4000; UID/GID 10001, no privilege escalation, ALL capabilities dropped | Configuration readback; not fresh outbound test |
| Fresh 18:00 ICT outbound probes | Secure GitHub/PyPI/npm/public-IP requests failed; internal LiteLLM returned its expected liveness body. Internet GitHub/PyPI/npm returned 200 | Public-IP Internet comparison also failed, so that pair is not independent proof of denial. DNS and relay paths remain separate checks |
| Anonymous report, proxied report and session API requests | Local gateway returned actual login-page content, with no test-backend content | Local HTTP boundary test; not a live cross-user report test |

Fresh outbound response records are retained in [rdt-egress-recheck-20261015.json](context-evidence/rdt-egress-recheck-20261015.json). No CronJobs were listed in namespace `llm`; this does not exclude in-process jobs, user scripts or publishers in other namespaces.

## Build verification experience

- Build 62692 stopped before push because Docker's daemon could not see the agent-side test bind mount. Tests are now packaged in the image and run from `/opt/dsh`.
- Build 62694 passed the executed catalog and routing tests but stopped at an overbroad string check: upstream's provider-ordering helper still mentions `deepseek-official`. That string alone does not create a selectable provider or external route. The built-image check now targets provider IDs and routable-provider declarations instead of sorting comparisons.
- Build 62696 succeeded for Azure revision `dadbab701f2547e11696c027606ef5580414f1de`. Its pushed image is `dsoreg-sm1-p1.bot.or.th/da-gpu-server/dsh-runtime@sha256:396fb2e862ad15731b6a49ac16efd7e15fa8e065379fe196a0c62cb21d031719`. Catalog, routing, registration-denial and isolated-routing tests passed inside that image. A temporary cluster pod ran the same tests successfully. No failed candidate was deployed by these build steps.

## Live gateway change and actual behavior

The gateway now runs the verified `396fb2e8…` image. Kubernetes service-account credential automount is disabled. The replacement used Recreate to avoid overlapping gateway instances with independent session maps and writers to the account/settings store. Existing users may need to sign in again; execution pools and model configuration were not restarted or altered by this gateway change.

The [live response record](context-evidence/rdt-gateway-live-20261015.json) confirms: registration POST returns 403; registration tab and form are absent; No Internet is checked by default; the credential store is byte-for-byte unchanged after the denied registration; anonymous report/proxy/session requests return the actual login form. Those requests do not test authenticated cross-user authorization. Running image ID matches the pushed digest and the replacement pod reports zero restarts.

Rollback gateway manifest: `C:\Users\skunpojt\rollback-pilot-hardening-20261015\gateway.yaml`. Execution pools still use `0505beb6…`, so their installed catalogs have not yet received the new image. The gateway change does not establish per-user isolation or approved RDT access.

## Required deployment and acceptance sequence

1. Build and inspect immutable candidate image; save gateway/runtime manifests and volumes for rollback.
2. Obtain approved pilot identities and exact scope-limited RDT snapshot/view from the owner. Existing accounts do not establish approval. For a database view, provision restricted database credentials separately; the snapshot-PVC option does not implement database authorization.
3. Provision private runtimes and map identities to fixed backends. Establish file/history ownership before migration. Preserve legacy volumes; do not copy shared history wholesale to every user.
4. Validate candidate routing, default No Internet, logout, session persistence, terminal, tools, attachments and authenticated report access before ingress cutover.
5. Test actual source writes and out-of-scope reads fail, while designated results storage works. Do not use production write attempts as a substitute for an approved test dataset.
6. Test user A cannot obtain user B's files, sessions, reports or attachments through HTTP, WebSocket, terminal or tools. Also test unauthenticated access and logout-session rejection.
7. Repeat external-denial tests for each protected worker. Audit DNS forwarding and shared model gateway egress/fallbacks; public HTTPS denial alone does not prove indirect leakage is blocked. Legacy DSH2/DSH3 must be explicitly included in or excluded from the pilot boundary.
8. Inventory and disable automatic exporters, scheduled publishers and external export credentials in pilot runtimes. Validate report routes with actual content, not status codes alone.
9. Record tested identities, payloads, results, time, image digest and deployed source revision. Only then revise the three-control decision to closed; assessor acceptance remains separate.

## Pending owner information

The user has been asked for the named pilot identities and approved RDT snapshot path/PVC or database view. These inputs remain pending. No final data access or history migration has been performed in this change.

## Rollback

Retain existing shared runtime/state PVCs and the gateway manifest until private-runtime acceptance passes. A rollback must restore the saved gateway routing and image, not merge private histories into the old shared store. Reauthentication is expected after gateway replacement. The model scheduling/context configuration is outside this control-hardening change.

## Current central-state correction — 15 October 2026

This supersedes earlier local-only active-history statements above. Secure durable sessions, attachments, storage, workspaces and logs now mount directly from `dsh/dsh_storage` on CIFS; credentials/profiles remain local. Internet remains separate. 43 cwd headers were corrected with byte-identical conversation frames; all 80 histories have readable cwd paths. Restart, exact session-file hashes, actual terminal WebSocket execution and network probes passed within the [recorded scope](context-evidence/central-state-live-20261015.json). Use the [new operator procedure and rollback guidance](CENTRAL_STATE_RESTORATION_20261015.md). Per-user isolation and approved read-only RDT access remain open; no ownership or RDT scope was inferred.
