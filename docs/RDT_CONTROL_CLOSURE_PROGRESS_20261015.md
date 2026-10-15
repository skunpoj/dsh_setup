# RDT pilot control closure: implementation and evidence

Updated 15 October 2026, 17:58 ICT. This supplements the original 13:03 assessment; it does not replace historical observations with later source tests.

## Current decision

The three controls remain partially satisfied. Source hardening is implemented and tested, but a new runtime image, per-user cutover, approved data scope and deployed negative tests are still required. No RDT access, ownership or pilot membership has been inferred from existing shared account stores.

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
