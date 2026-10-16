# Per-user isolation — synthetic live canary, 16 October 2026

Two disposable users, `iso_alice` and `iso_bob`, exercised four private runtimes: one No Internet and one Internet runtime each. This was a separate live candidate, not a migration of existing Production users. All 80 legacy histories remained unchanged.

## Boundary and actual configuration

The successful namespace was `dsh-iso-20261016-131912`; the first attempt used `dsh-iso-20261016-130900`. Neither had a public Ingress. A private gateway authenticated the test users and bound each login to its identity and selected environment. Each runtime had its own workspace, state, launch token and non-root process. Secure durable paths were new CIFS siblings under `dsh-isolation-tests/<namespace>/private/<identity-hash>`, outside the legacy `dsh` tree. Internet had separate local volumes and no synthetic source mount. A temporary operator initializer created fixtures and was removed before runtime testing.

The candidate used the pinned build-62702 runtime image, digest `sha256:96be6e7fad0a1d456484bacfed45612c3d3ba95290a9f59a03eb612d50a4efc1`. The corrected gateway source was mounted through a candidate ConfigMap; this did not rebuild the image or patch the existing Production gateway. Saved configuration readback records mounts, image IDs and source hashes.

## Failures found and corrected

Initial Secure setup stalled while using a new read-only local package-cache claim and a source alias of the writable central claim. The revised setup used an empty read-only ConfigMap as its unused cache fixture and a distinct CSI PV/PVC identity for the read-only source. This resolved the observed startup stall; it does not establish a general CSI incompatibility or validate package installation.

The first functional test found a real forwarding defect: custom HTTP routes could pass client-forged `x-dsh-user` and `x-dsh-internet-access` headers to the application. Raw WebSocket forwarding also needed canonicalization. A regression test against the original source reproduced `mallory` instead of authenticated `alice`. This showed forged identity metadata reaching an application; it did not establish a successful cross-user history disclosure.

The correction binds identity centrally after authentication for both HTTP and WebSocket requests. It replaces normalized headers and removes duplicate mixed-case raw headers before appending one canonical user/environment pair. The revised source passed the live canary and the network regression tests. **Existing Production still has the older gateway source; deploying this correction there remains a separate rollout.**

## Recorded acceptance results

Before restart at 13:20:52 ICT and after restart at 13:21:49 ICT, the following checks passed in all four runtimes:

| Actual behavior | Before | After replacing all four runtime processes |
|---|---|---|
| Own report with exact synthetic content | 4/4 | 4/4 |
| Own attachment-file fixture through authenticated app proxy | 4/4 | 4/4 |
| Real DSH session listing and page read | 4/4 | 4/4, same IDs and titles |
| Other user's history denied | 4/4 | 4/4 |
| Other environment's history denied | 4/4 | 4/4 |
| Forged HTTP identity rejected | 4/4 | 4/4 |
| Duplicate/mixed-case forged WebSocket identity rejected | 4/4 | 4/4 |
| Actual terminal command reads private marker at UID 10001 | 4/4 | 4/4 |
| Anonymous requests return login without private marker | 4/4 | 4/4 |

Four real DSH histories were created through `session/create` and `session/rename`. Pod UIDs changed during restart. Held gateway cookies continued to work while backend launch-token caches refreshed. Registration was denied without provisioning an account. Attachment evidence concerns stored synthetic files, not the upstream upload or image-processing workflow.

Each worker ran at UID 10001 with no capabilities or service-account token. The legacy tree and neighbor workspace were absent. Direct HTTP requests to another user's runtime Pod IP were denied in all four cases while authorized gateway reads succeeded.

Both Secure workers read two synthetic CSV rows totaling 300. Append, delete and create attempts all failed with `EROFS` (six failures across two workers); source hashes stayed unchanged. An unmounted sibling fixture was inaccessible. Internet workers had no `/data/rdt`. GitHub requests timed out in both Secure workers and returned HTTP 200 in both Internet workers. These are bounded network tests, not exhaustive DNS, relay, IPv6 or provider-log assurance.

## Legacy preservation and cleanup

Read-only fingerprints before the first attempt and after the final attempt matched: **80 unique histories, 82 generation files**, aggregate SHA-256:

`7bb4aa235893e12b0bf545a4f87e00a3a6df2a656e33acdb5231c8def460c317`

The fingerprint combines ordered relative filenames and whole-file hashes. No legacy history was assigned, copied to a test user or restored to manufacture equality. Both candidate namespaces now have zero Pods and all five deployments scaled to zero; temporary Kubernetes Secrets were removed. Synthetic PVCs and files remain for audit. Existing Production mounts, users, auth store and inference were not changed by this test.

## What this does not close

The mechanism passed synthetic candidate acceptance. Existing Production shared pools are still shared; no real-user cutover or legacy ownership decision occurred. Actual RDT scope, source identity and owner approval remain unknown, and no real RDT was used. Broad legacy mounts must not expose new private trees during a future cutover. Shared inference credentials/provider logs, exhaustive egress paths, package promotion/install, upstream attachment processing, node-loss recovery and inference performance were not assessed here.

Evidence: [successful canary](context-evidence/user-isolation-canary-20261016.json), [first attempt and correction](context-evidence/user-isolation-canary-first-attempt-20261016.json). Reproduction entry point: `scripts/run_isolation_canary.py`; resource validation refuses Production namespaces, Production claims and legacy subpaths. Use fresh disposable identities and a unique namespace, never real-user histories.
