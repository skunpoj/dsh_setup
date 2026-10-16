> **Superseded operational snapshot:** the later 16 October private-user, Kerberos-runtime and datalake-aware network rollout is recorded in [the current security report](DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.md), [runtime acceptance](context-evidence/kerberos-runtime-live-62743.json) and [fresh performance](context-evidence/performance-private-live-20261016.json). Preserve the observations below as historical evidence; shared-pool and unidentified-RDT-mechanism statements are no longer current. Real RDT uses Kerberos/Livy/Spark, independent of DA_WORKSPACE.

# Live review, correction and performance — 16 October 2026

## Conclusion and the outdated storage statement

The earlier statement that active state is only local and needs continuous central synchronization is superseded by the live mounts. Secure `/workspace` is CIFS at `//bot.or.th/cfs/FILESERV/DA_WORKSPACE/workstation`, root `/dsh`. Its sessions, attachments, storages, workspaces and logs are direct CIFS submounts under `/dsh/dsh_storage/<directory>`. They write centrally rather than waiting for a copy job. The `/state` parent remains local XFS for configuration and credentials. Internet state remains intentionally separate and local. Central storage is not a backup or disaster-recovery guarantee.

The two-user synthetic canary passed isolation and persistence. Existing Production still routes to shared pools. Actual RDT is not mounted at `/data/rdt`; no unidentified data source was granted. Therefore, synthetic mechanism acceptance and gateway correction are complete within their tested scopes, but all three Production pilot controls cannot be declared closed.

## Correction deployed in this review

The tested identity-header correction now runs in the Production gateway. Its immutable ConfigMap is `dsh-gateway-source-c9737befbe88`; command is `node /gateway-source/auth_proxy.js`; running source SHA-256 is:

`c9737befbe880f77e65b97cf4ec186883a26cb292267be55c18481253259c988`

The runtime image is unchanged, build 62702 digest `sha256:96be6e7fad0a1d456484bacfed45612c3d3ba95290a9f59a03eb612d50a4efc1`. This is a tracked source overlay, not a rebuilt image. A future replacement must retain the overlay or use a new image containing the correction. Applying only the older base manifest would drop it. The tracked strategic-merge patch and rollout script record that dependency.

Only the gateway was replaced. Execution pools and inference were not restarted, and history/workspace mounts were not changed. Gateway replacement can interrupt connections and require fresh login; preservation of old gateway cookies was not claimed or tested here.

Actual temporary-account checks before and after the rollout passed in both environments: fresh login, correct environment binding, authenticated HTML and logout button, secure cookies, history listing (Secure 80; Internet 0), terminal page and invalidation after logout. Temporary credentials were removed and other accounts verified unchanged. These checks include terminal-page access; actual terminal commands and forged HTTP/WebSocket behavior were established in the earlier synthetic candidate using this exact source, not repeated as Production command/attack tests during this rollout.

An exact pre-change Deployment specification is saved privately at `C:\Users\skunpojt\outputs\dsh-live-review-20261016-identity\gateway-before.json`. The rollout script replaces the complete saved specification if its readback or acceptance fails, including removal of overlay-only annotations and volumes. Mocked tests verify that restoration and cleanup on a running-source hash mismatch, and refusal before Kubernetes access when source differs from the canary. No failure occurred and that recovery branch was not exercised in this rollout. Reverting the gateway does not require reverting histories or the model. The immutable ConfigMap remains for reproducibility.

All **80 legacy histories in 82 files** retained aggregate SHA-256:

`7bb4aa235893e12b0bf545a4f87e00a3a6df2a656e33acdb5231c8def460c317`

## Current runtime and network behavior

| Runtime | Observed execution | Representative direct HTTPS | Data boundary |
|---|---|---|---|
| Secure | UID 10001, no mounted Kubernetes service-account token | GitHub/PyPI/npm all timeout, curl 28 / HTTP 000 | Original CIFS workspace and durable subdirectories; no `/data/rdt` source |
| Internet | UID 10001, no mounted service-account token | All three HTTP 200 | Separate local workspace/state; no protected CIFS or `/data/rdt` |
| DSH2 (`dsh-user2`) | UID 0; service-account token mounted | All three HTTP 200 | Legacy local workspace; not a restricted pilot environment |
| DSH3 (`dsh3`) | UID 0; service-account token mounted | All three HTTP 200 | Legacy local workspace; not a restricted pilot environment |

These are specific network observations, not exhaustive leakage assurance. DNS, proxies, allowed-service relays, IPv6, downstream inference logs and every execution path still require assessment. DSH2/DSH3 cannot be presented as covered by Secure's acceptance. Their root startup installs software at runtime; abruptly denying their Internet or changing UID would risk breaking startup and file access. This review did not silently convert them or claim they are ready for RDT.

## Context, concurrency and measured speed

Live SGLang arguments remain: context **1,048,576**, static memory **0.90**, running-request ceiling **16**, prefill chunk **1,024**, maximum prefill **2,048**, mixed chunks and prefill/decode interval **4**. LiteLLM DeepSeek aliases advertise **131,072 input** and **8,192 output**; the existing proxy total-token clamp and DSH guardrail remain 128K. No configured LiteLLM fallback was found in the inspected model configuration. That is configuration evidence, not an exhaustive provider/relay audit.

The 1M backend ceiling is different from the DSH product budget. It does not promise 16 simultaneous maximum-length requests or responsiveness during near-1M work. Earlier 1M completion used an earlier scheduler profile; the current fairness profile has bounded mixed-load evidence, not revalidated near-1M contention. This review did not change those limits or repeat a disruptive long-context test.

Fresh synthetic streaming requests from Secure through LiteLLM returned exact expected content:

| Sample | First token | Full completion | Effective output speed |
|---|---|---|---|
| Three short sentinel replies | 0.111–0.114 seconds | 0.230–0.231 seconds | About 21.6–21.8 tokens/sec for five-token replies |
| Two concurrent 119-token replies | 0.115–0.116 seconds | 3.381–3.386 seconds each | 35.15–35.20 tokens/sec per request |

Both concurrent requests output the exact integers 1 through 40 and stopped normally. This demonstrates overlapping service for this small workload. Effective output tokens/sec divides completion tokens by full elapsed time, including queue/prefill/network overhead; it is not steady-state decode throughput or an SLA. It does not measure DSH agent turns, tool runtime, large existing histories, long-context retrieval or sustained multi-user load.

A second sample submitted a fresh synthetic **24,047-input-token** request and three repeated short sentinel requests while it was still running. The longer request returned the exact sentinel in **4.987 seconds** (first token 4.836 seconds). All three short replies completed **before** that longer request finished: **0.466, 0.581 and 0.588 seconds**, with first-token times 0.183–0.298 seconds. This directly establishes responsiveness during the recorded 24K workload. The short prompt was repeated and may benefit from prefix caching; this is not an uncached adversarial workload or near-1M fairness test. The second two-request sample again measured about 35.1 effective output tokens/sec each.

A later GPU snapshot showed four GPUs with 95,830 MiB each, 90,720 MiB used each and 0% utilization at that instant. Free memory in an idle sample is not proof of safe maximum-length concurrency.

## Remaining decisions and safe disposition

| Item | Verified disposition | Remaining work |
|---|---|---|
| Original central persistence | Live direct CIFS mounts; 80 histories preserved | Storage-server recovery/ACL assurance is separate |
| Gateway identity binding | Canary behavior tested; exact source deployed; post-rollout authentication passed | Carry overlay into future image builds; broader app-route coverage |
| Per-user isolation | Two synthetic users/four runtimes passed before/after restart | Existing shared Production pools are not cut over |
| Legacy ownership | All 80 unchanged | Do not guess ownership or copy histories into every new account |
| Read-only source | Six synthetic mutations rejected, source unchanged | Real RDT source and dedicated access identity not identified or granted |
| External-leakage control | Secure public HTTPS denied; internal inference works | DNS/relay/worker review and infrastructure acceptance |
| DSH2/DSH3 | Legacy root and Internet behavior recorded | Separate pinned-image, state-preserving migration and acceptance before RDT use |
| Results containment | Synthetic private access tests passed | Named real-user provisioning and Production authorization/export-path acceptance |

No additional history ownership question is needed to retain current storage or test synthetic mechanisms. Unknown owners and source scope remain explicit deployment constraints; they are not filled with guessed permissions. The next real-user cutover should start confirmed identities with empty private histories, retain legacy records in their existing boundary, and prevent broad legacy mounts from exposing new private trees. It must not silently remove current users' access to their existing work.

## Reproduction and evidence

- `scripts/rollout_gateway_identity.py`: exact canary-source hash gate, saved specification, pre/post behavior and rollback on failure.
- `scripts/review_live_status.py`: selected public configuration fields, mount table and bounded egress probes; does not export credential values.
- `scripts/measure_live_responsiveness.py`: three short and two concurrent synthetic streaming calls without creating histories.
- [Gateway rollout](context-evidence/gateway-identity-live-20261016.json), [current status](context-evidence/status-live-20261016.json), [performance sample](context-evidence/performance-live-20261016.json), [24K mixed-load sample](context-evidence/performance-mixed-live-20261016.json).
- [Two-user acceptance and initial failure](USER_ISOLATION_SYNTHETIC_TEST_20261016.md): separate candidate evidence and limits.
