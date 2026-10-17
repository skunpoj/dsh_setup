# Shared LLM — 1M Setup, Performance and Operational Limits

## Latest admission and cancellation correction

The controlled occupied-slot retest passed: **1,007,704 input tokens**, **119 output tokens**, the full correct 1–40 answer and persisted prompt, with **0 retries**. Total DSH time was **1551.75 seconds**, including **315.74 seconds waiting for admission** and **1226.79 seconds preparing context**. The answer streamed in **3.53 seconds**, approximately **33.42 output tokens/second**. This rate excludes queueing and preparation.

**46/46 overlapping ordinary DSH replies** were exact with zero retries, taking **4.05–9.12 seconds** (median 5.59). A third long nonstreaming request to the loopback final-wire guard received HTTP 429 in **0.34 seconds** while the active and waiting positions were occupied. Of these, 38 probes started after the hold released, during the real long-request work; that subset took 5.07–9.12 seconds. The intentional 320-second hold is test overhead, not a GPU throughput measurement.

Actual DSH cancellation of a 147,674-token active request freed admission in **1.48 seconds after cancellation**. A separate 147,673-token waiting request was cancelled and cleaned up while the main near1M request retained its own lease. The GPU pod identity/image stayed unchanged with **zero restarts**. CUDA allocator memory-mapping OOM warnings were observed near the final prefix steps, but the request completed and ordinary replies continued. This verifies the recorded admission/cancellation case, not additional GPU memory headroom or two full-1M requests. Mounted middleware bytes match the tested source. All **68 targeted Linux tests** and **42 portable-bundle tests** passed without skips.

[Sanitized measurement record](context-evidence/admission-responsiveness-20261017.json). Earlier retry-bearing and invalid-fixture records remain preserved; this result does not retroactively make them passes.

See [admission design and test](ADMISSION_RESPONSIVENESS_20261017.html). Streaming preparation now returns early SSE comments; cancellation no longer has to wait for response headers. One long request may wait up to 1,500 seconds in a bounded FIFO position; ordinary requests bypass long admission. This final-wire route supersedes the earlier 300-second waiting policy recorded below. Legacy callback defaults remain unchanged.


## Complete application redeployment and current-source mixed test

The [deployment, preservation and functional review](DEPLOYMENT_AND_FUNCTION_REVIEW_20261017.html) covers the subsequent sequential replacement of all twenty main runtimes, both legacy instances, the gateway and resolver. It records original-file/history checks, private isolation, all-worker networking, actual client replies, offline dependency installation and complete HTML rendering checks. The main runtime checks verified 31,897 files and 10,257,934,187 original bytes with no content failures; the original owner's 80 histories and admin's independent 83 histories remain separate.

On the current forwarding source, a **263,691-input-token** DSH request returned its exact persisted answer in **274.01 seconds**, with **zero retries**. Paired 119-token DSH replies during that work completed in **4.58–5.57 seconds**; eight simultaneous replies in **6.59–6.62 seconds**; sixteen in **10.26–12.01 seconds**. The sixteen-request burst achieved **134.20 aggregate effective output tokens/s**, including client-launch overhead. These are bounded application measurements, not an SLA or sixteen near-1M requests. The worst paired stream gap was 779 ms; small replies are not guaranteed uninterrupted GPU time. See the separate review for exact scope, preserved failed diagnostics and the final near-1M retest result.

An earlier 263K test succeeded only after one DSH retry following the 300-second admission deadline. Its older aggregate pass flag did not check long retries. That record is preserved as retry-bearing; the subsequent current-source acceptance checks retries explicitly. A long thread being alive can mean queued admission, so mixed-workload claims must also establish actual preparation overlap.

The final current-source DSH capacity retest counted **1,007,702 input / 119 output tokens**, returned the complete expected 1–40 sequence and persisted it in **2088.27 seconds**, with **2 retries**. **60 ordinary DSH replies** completed exactly alongside the active long turn in **5.06–8.66 seconds**. This is capacity/transport/output-budget acceptance, not a new realistic analytical-quality review or two-full-1M test. The successful attempt included 243.67 seconds of admission wait and 1,227.76 seconds of preparation; the answer then streamed in 3.51 seconds (approximately 33.65 output tokens/second). The whole-turn duration also includes the preceding busy retries. These are different measures, not 34 minutes of decoding. The original combined zero-retry/latency gate did not pass and its raw result is retained. The long turn encountered occupied admission capacity before retrying; these timings include that wait. A correct eventual answer is not relabelled as a zero-retry cold run.

## Fresh GPU startup and bounded 1M acceptance — 17 October 2026

**Fresh existing-node GPU acceptance, 17 October 2026:** a newly started model served **1,007,695 actual DSH input tokens**, returning the complete expected answer in **20m48s** with zero retries and no GPU restart. **80/80** bounded ordinary API replies passed; **6/6 actual DSH replies during near-1M preparation** completed in **6.61–7.14s**, with approximately **23–37 stream tokens/sec** per reply. A 16-client API burst passed in **5.51–10.08s**. One overlapping gateway reload caused five retries during a successful near-1M tool continuation; fresh short-tool and output-budget checks then passed without retries. Cancelled retained-history replays are recorded separately. [Measured results, scope and lessons](FRESH_GPU_ACCEPTANCE_20261017.html).

The fresh model profile uses existing cached weights and the existing authenticated gateway/database; it is not a fresh-cluster, new-download or new-storage acceptance. The cold and mixed-load measurements used the prior gateway source; the later gateway reload and follow-up tests are separately identified in the new report. The model retained its identity/image with zero restarts through the sequence. Startup took about ten minutes. The Deployment progress deadline is now 2,100 seconds, aligned above the startup-probe budget, without another model restart.

## Portable infrastructure counterpart

The [sanitized GPU/LiteLLM/1M bundle](../gpu-stack/README.md) contains reproducible candidate manifests, actual guarded routing and scheduler sources, private Secret references, prerequisites, qualification and rollback. It omits site endpoints and storage identities. Its initial qualification was source/template-only; the later existing-node model startup and bounded long-context acceptance are documented above. A complete fresh-cluster installation remains unqualified. See the [dashboard coverage map](CENTRAL_DASHBOARD_SCOPE.md) for current versus planned telemetry.

## Ordinary DSH responsiveness during near-1M work — 17 October 2026 ICT

**Earlier 17 October scheduling/SDK checkpoint:** foreground scheduling preserved the 1,048,576-token limit while improving ordinary DSH responses. The measurements in this subsection belong to the earlier immutable forwarder `litellm-interactive-cd9a424fa8e4`; the subsequent race/timing correction uses `litellm-interactive-494f6b16db5d` and is covered by the current-source review above. The GPU was not restarted by those gateway changes. The SDK-budget overlay required controlled restarts of all 20 main CPU runtimes; original history IDs and all 40 temporary workspace/state markers survived. All 82 preserved owner session files remained byte-identical. Networking and ownership/mounts were preserved.

### Cause and design change

The saved `can u access internet` turn sent 8,985 tokens including DSH context. It took 5.17s to first text and 33.09s to deliver 114 output tokens, with no tool call or retry. Its timings alone do not identify every cause of that historical 38.3s turn. A fresh controlled DSH test reproduced long-prefill contention: the same 119-token answer took 5.63s idle but **10.63–11.64s** during approximately 264K work. Backend logs showed long prefill batches interleaving with short decoding. The streaming output rate dropped to **11.34–14.03 tokens/sec**. Earlier eight-token-marker tests understated this effect on paragraph-length answers.

Ordinary requests below the existing long-admission boundary register a foreground lease until their real stream finishes. Before each bounded **2,048-token** long-prefix warming step, the forwarder lets those streams drain. Each wait is capped at **8 seconds**, after which long preparation may take a step under continuous short traffic. Classification uses the full reconstructed conversation plus output budget, not the newest message alone. A few words added to an existing >128K history still use long admission. Ordinary requests remain parallel. Completion, failure, cancellation and duplicate cleanup release ownership safely. Warm summaries record foreground yield time without prompts or credentials.

The **1M total budget**, one >128K admission slot, 8,192-output ceiling, 256-token reserve, exact final-wire counting and backend cap of 16 remain unchanged. This is cooperative yielding, not GPU-kernel preemption. An in-flight prefill can still delay first text; sustained foreground traffic lengthens long preparation and can encounter existing client deadlines. Eight seconds is a per-opportunity preparation-pause limit, **not a response SLA**. State is local to the single forwarder; keep one replica with Recreate until admission is distributed.

### Client budget regression found and fixed

The cold near-1M mixed test ingested **1,007,685 input tokens**, but initially returned only `L`: the client SDK's character-based estimate silently capped generation at one token despite backend space remaining. This **failed answer is preserved**, not relabelled as successful capacity acceptance. A source-hash-pinned Node loader hook now leaves output budgeting to the exact fail-closed internal tokenizer **only** for the managed DeepSeek aliases/provider/origin and the true 1M catalog. Explicit smaller caller limits remain honored; unrelated providers retain their original SDK checks. An actual over-budget request was still rejected by the managed gateway with HTTP 400 and the exact 1M-budget error. Upstream SDK drift stops qualification. All 20 main runtimes received the read-only managed overlay, with original history IDs and all 40 persistence markers verified across restart. The base image and GPU process were not replaced. Future image builds now test the SDK contract; no new image was built during this rollout. The current read-only transport/budget overlay is `dsh-managed-transport-ced48d44ec3a`, on the existing pinned image.

The exact frozen near-1M prompt was retested after the client fix and returned the complete marker in **6.08s**, using retained backend cache. A fresh ~264K cold DSH mixed test then passed on the final client/forwarder combination: the long turn completed in 123.62s while four paired replies completed in 5.61–6.09s. The installed Node loader hook and explicit smaller-output caps were also tested against the actual SDK. **A second cold near-1M full-answer run was not performed after this SDK correction.** The 28 near-1M-overlap short samples below were measured with the new scheduler before the client-budget correction; the separate final-configuration mixed results are also recorded in the JSON.

### Actual DSH tests on the deployed change

| Case | Recorded result |
|---|---|
| Idle, same 119-token answer | 6.60s total; 3.51s streaming |
| 20 paired replies during the cold near-1M request | All exact and persisted; **4.05–8.63s** total; first text **0.61–5.11s** |
| Paired streaming output rate | **36.46–36.92 tokens/sec**; includes delivery, not isolated GPU decode |
| Eight simultaneous ordinary DSH replies | 8/8 exact and persisted in **7.66–8.68s**; long request still active |
| Late preparation | Two simultaneous replies at each observed cached-prefix stage above 800K and 950K; all exact while long work remained active |
| Cached near-1M retest after client fix | **1,007,685 input / 7 output**, exact persisted marker in **6.08s**, zero retries; initial cold one-token failure retained |
| Model continuity | Same model pod UID/image, zero restarts |

The 105/105 API stress sweep below predates this scheduling change; this acceptance adds actual DSH mixed-workload tests and does not repeat the 16-way API sweep. Times include agent RPC and polling overhead. Before/after ordinary prompts and their 119-token answers are identical, but the long inputs differ in length. These bounded synthetic tests do not establish a latency SLA, sixteen near-1M requests, browser-interface qualification or new analytical accuracy. The earlier realistic source/citation test remains separately recorded below. Explicit turn intervals and late-stage observations establish overlap; opening this report does not run new tests.

### Reproduction, rollout and rollback

Use `scripts/probe_dsh_stream_latency.py` only inside a reviewed disposable DSH runtime with ephemeral storage. It creates synthetic histories and records persisted answers, input/output usage, first-text and streaming times, retries and tool calls. Never run it in another user's runtime.

`rollout_interactive_scheduling.py` defaults to a plan. Supply the reviewed current source hashes, a new private output directory and `--apply` after owned long work finishes. It checks singleton/Recreate and a free long lease, clones the current configuration, and changes only its volume reference. It preserves authentication, network settings, model deployment and user volumes. Startup/readback failure restores the old reference. For a later performance regression, finish/cancel owned tests and confirm admission is free before restoring that saved reference; then test real inference. For the managed SDK budget overlay, use `scripts/rollout_managed_budget.py` with the reviewed previous transport hash and a new private checkpoint directory. It refuses active user agents, replaces only the transport ConfigMap reference, verifies actual history IDs, two durable markers per runtime and the installed SDK hook, and restores the previous reference if that runtime fails. Do not restore older user files. No rollback was needed in this passing run.

[Complete timing, overlap and policy record](https://github.com/skunpoj/dsh_setup/blob/main/docs/context-evidence/interactive-scheduling-acceptance-20261017.json).

## Main client acceptance and current controls — 17 October 2026 ICT

**DSH, Claude Code and TrueForge can use near-1M context through the internal DeepSeek/LiteLLM route in the 20 main runtimes.** This update adds actual Claude CLI and TrueForge API tests to the previously accepted DSH result. Large client cases used disposable storage on the current runtime image against the Production inference route; configuration readback and small default-client checks then covered all 20 main runtimes. These were not twenty separate cold near-1M runs. It does not infer capacity from a model label or metadata alone.

| Client | Configured total context | Actual capacity case | Measured elapsed time |
|---|---:|---|---:|
| Main DSH | 1,048,576 | Previously accepted unedited repository review: 1,007,329 input / 3,798 output; 1,647-word narrative | 123.28s cached correction after three source-backed correction turns; the initial 1,342.61s cold draft failed narrative checks |
| Claude Code 2.1.301 | 1,000,000 client window via default `[1m]` mode | **987,678 input / 10 output**, exact two-marker answer | **1158.81s** |
| TrueForge 0.179.2 | 1,048,576 | **987,024 input / 10 output**, exact two-marker answer | **1162.20s** |
| TrueForge retained conversation after network/gateway handover | 1,048,576 | **987,047 input / 9 output**, exact follow-up, both turns read back from storage | **6.55s** |

The cold Claude/TrueForge task reads two sentinel values from the frozen repository/document archive. It verifies request capacity and transport; its ten-token answer is not a long analytical-quality test. DSH's separate 1,647-word source/citation review supplies the longer-output task evidence. The cold runs spend most elapsed time preparing the large input in bounded chunks. The fast retained-conversation case demonstrates cache reuse for that case; different or evicted prefixes can require preparation again. Do not interpret ten output tokens divided by nineteen minutes as GPU decoding throughput.

**Defaults and deadlines corrected:** all 20 main runtimes now select Claude's `deepseek-v4.1-flash[1m]` by default, with a one-hour API deadline. TrueForge now sets its **model-specific** headers/body deadlines to one hour and model HTTP retries to zero; generic outbound timeouts alone did not cover model calls. A real second long TrueForge request received the busy error after **300.61s** while the first long request continued. Main ingress read/send deadlines are one hour and response buffering is off. Its hosts/backends are unchanged. These are operator-owned read-only settings on the existing runtime image, through `dsh-harness-policy-1456fd35454f`; no GPU-model reload was needed.

The common gateway caps output at **8,192 tokens**, counts complete input including system/tool structure and reserves **256 tokens**. A 1M context includes input and output. Claude's 1,000,000 client window is narrower than the backend's 1,048,576 ceiling. Full 8,192-token output near the ceiling, near-1M vision, real near-limit automatic compaction, and a fresh external-browser near-1M interaction are not qualified by these cases. TrueForge's optional code sandbox remains disabled; these tests do not enable nested namespaces or privilege.

### Earlier 17 October API concurrency and output rate

**105/105 expected outputs passed across 18 stages.** Fifteen burst stages cover three repetitions at each concurrency below; three mixed stages combine a roughly 24K, 96K or 120K input with three small requests. The numeric-output comparison ignores whitespace. These are shared-gateway API calls, not sixteen Claude/TrueForge processes or sixteen near-1M requests.

| Concurrent ordinary requests | Passed burst calls | Effective output tokens/sec per request | Aggregate output tokens/sec |
|---|---:|---:|---:|
| 1 | 3/3 | 31.88–32.26 | 31.86–32.24 |
| 2 | 6/6 | 31.50–33.56 | 53.56–62.97 |
| 4 | 12/12 | 29.59–32.08 | 92.78–123.00 |
| 8 | 24/24 | 22.17–26.76 | 162.09–169.57 |
| 16 | 48/48 | 13.53–18.33 | 211.32–235.06 |

Rates include queue, prefill and networking; they are not isolated GPU decode speed or an SLA. After the final network handover, two further ordinary requests passed at **31.72 / 33.53 output tokens/sec each**, **55.96 aggregate**, in **2.52 / 3.55s**. During TrueForge's active cold run, two actual Claude processes returned exact replies in **2.22 / 2.23s**, and an actual DSH conversation returned its exact persisted reply in **6.06s**, including polling. The long-run monitor also recorded 18 small gateway samples alongside Claude and 18 alongside TrueForge; their samples are reported separately from strict event-level overlap instrumentation.

**Operating rule:** backend running cap **16**, but only **one request above 128K** is admitted at a time. A second waits up to 300 seconds per gateway attempt, then receives a busy error. The real TrueForge busy case is qualified above; client-wide retry behavior is not a universal 300-second SLA. Short requests remain schedulable; token usage and temporary attention memory still constrain throughput. Keep the shared forwarder at **one replica with Recreate**: its admission file lock is local to that process/pod. Scaling it requires a genuinely shared admission mechanism first. Recovering GPU allocation warnings were observed; memory remains tight.

### Local risk-control changes and safe setup

The 20 runtime profiles and 40 managed policy files were read back; all match the intended values/bytes. Forty workspace/state markers survived their controlled replacements. Actual runtime login/session-list and default Claude calls passed. These are runtime-launch/RPC checks, not fresh human-password login tests. The public TLS login page remains available with No Internet as default.

No Internet public-domain/direct-IP probes failed from all ten corresponding runtimes; all ten Internet runtimes retained public connectivity. Both environments reach LiteLLM but cannot directly reach the GPU backend. The shared gateway and LiteLLM now use approved internal DNS names plus a strict `dsh-u-<16 hex>-secure/internet.llm.svc.cluster.local` rule for newly provisioned runtimes, and service-specific egress policies; public DNS and public TCP probes failed. Model, embedding and database providers have deny-egress policies. Required private application, database, model and embedding behavior passed; no model restart occurred. Existing AD/datalake permissions and Livy/Spark availability were preserved.

Use `scripts/rollout_harness_context_policy.py` with an explicit main-runtime allowlist and a new private rollback directory, first as a plan and then with `--apply`. If the existing resolver source differs from the reviewed new source, upgrade it first with `refresh_internal_dns_policy.py` and the expected current-source SHA-256; an unexpected source hash stops the rollout. Use `scripts/rollout_shared_inference_boundary.py` to extend the explicit internal DNS list, permit its callers, change shared-service DNS, and only then apply egress policies. Each run needs a new private checkpoint directory outside Git. **Do not apply the shared egress YAML before configuring filtered DNS.** `k8s/shared-inference-dns-settings.json` records the desired pod DNS settings; it is not a standalone Deployment manifest. The existing bootstrap templates must not be reapplied over private ownership/routing. Old resolver ConfigMaps remain for existing Kerberos mounts and rollback. Newly approved private runtimes resolve through the narrow fully qualified naming rule; short unqualified names and appended public suffixes are not dynamically permitted. Generated gateway manifests also inherit filtered DNS settings, so a future reviewed user cutover does not silently revert to unrestricted DNS. CoreDNS was checked as authoritative for the private cluster zone. A temporary new Service demonstrated resolution without a static allowlist addition, then was removed. `refresh_internal_dns_policy.py` requires the reviewed current resolver hash for future source upgrades; it replaces only resolver configuration and saves a private checkpoint.

The network rollback procedure is `scripts/rollback_shared_inference_boundary.py` with the saved checkpoint directory; it defaults to inspection, and `--apply` restores only the recorded DNS/network changes. It does not restore user files or restart the GPU model. Per-runtime policy rollback uses that runtime's saved deployment specification. These recovery artifacts are prepared; an actual network rollback was not required. Model assets must be staged before a provider starts; a clean GPU-model restart under the final egress policy was not performed in this rollout.

**Scope still matters:** remote Spark worker egress remains the explicitly retained exception. Sandbox-only grants, protected-source write restrictions, deletion recovery and endpoint/privileged-user handling need the relevant owners; preserving existing AD permissions cannot be called enforced read-only access. Legacy DSH2/DSH3 have a separate migration/acceptance scope and are not included in this 20-runtime client qualification. The [three-risk report](DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.html) explains these controls without embedding benchmark logs.

[Scoped client/control summary](context-evidence/harness-1m-acceptance-summary-20261017.json) · [bounded stress record](context-evidence/harness-1m-bounded-stress-20261017.json) · [final runtime readback](context-evidence/harness-1m-final-runtime-readback-20261017.json) · [post-handover TrueForge persistence](context-evidence/harness-1m-trueforge-post-boundary-and-persistence-20261017.json) · [cleanup and unchanged model](context-evidence/harness-1m-cleanup-final-verification-20261017.json).

## Earlier settings audit — before the new client tests

**Settings reconciled with live deployment, 17 October 2026 ICT:** fresh readback checked all 20 main profiles and running image IDs, compaction policies, provider timeouts, the gateway's single-replica/Recreate strategy and targeted retry policies, installed forwarding-source hashes, and the model arguments. They match the architecture table below. A fresh authenticated request returned the exact expected reply. Historical performance/quality tests remain dated saved observations; they were not rerun during this documentation audit. This is not a fresh verification of every platform security/storage feature. [Live settings readback](context-evidence/documentation-live-settings-review-20261017.json) · [test-record reconciliation](context-evidence/documentation-result-reconciliation-20261017.json).

The main **DSH → LiteLLM → SGLang** route supports **1,048,576 total tokens**, with an 8,192 output ceiling and a 256-token reserve. All 20 main DSH runtime profiles were read back, and the current managed-tools image was qualified using a temporary DSH runtime with isolated synthetic storage against the Production inference service.

The earlier clean current-image cold DSH capacity request used **1,007,689 input + 8 output tokens**, returned the exact persisted answer in **1,173.92 seconds (19m34s)**, while 18 ordinary DSH replies completed in pairs during the long run. After the gateway retry correction, a real write/read tool continuation used **1,008,103 input tokens** and passed in **20.16 seconds**. This qualifies the recorded main DSH cases, not the separate Claude Code or TrueForge clients.

The earlier 128K statements described an incomplete deployment: the backend had been raised while DSH/LiteLLM guardrails remained lower. The [earlier review](LLM_128K_BASELINE_BEFORE_1M_20261016.md) and failed/intermediate trials are retained. Initial near-1M successes took about 19 minutes and required three automatic timeout retries. The final scoped Node transport correction removed those retries in both the delayed fixture and the real cold test.

**Earlier qualification memory evidence:** the preceding-image cold run recorded **1,460 recovering allocator mapping warnings**, with a minimum warning-reported free memory of **9.75 MiB** while attempting a 20 MiB mapping. No checked fatal exception or model restart occurred; ordinary DSH inference still returned correctly after warnings appeared. This passing test does not establish comfortable memory headroom, unrestricted long concurrency or a service-level guarantee. [Final cold acceptance and warning summary](context-evidence/final-managed-1m-acceptance-summary-20261016.json) · [near-1M tool continuation](context-evidence/final-managed-1m-tool-continuation-20261016.json).

## Generated narrative accepted without editorial repair — 17 October 2026 ICT

**The unedited DSH response passed the declared source-bound task after three source-backed correction turns in DSH.** It used **1,007,329 input / 3,798 output tokens**, generating a **1,647-word narrative** and a seven-claim evidence ledger. All **15/15** answer/source/quotation checks, **52/52** narrow narrative ranges, **7/7** known source-branch regressions and the separate narrative source review passed. **Zero editorial changes** were applied to the accepted response.

The actual DSH turn took **123.28s** with **0 retries**. **2** exact persisted short DSH replies completed in pairs during admitted work at **2.03–2.03s**. Model identity/restart count stayed unchanged; **4 recovering mapping warnings** still indicate tight memory margin. Cleanup/archive readback and post-cleanup inference passed.

This corrects the previous gap: editorial repairs had fixed the publication while the generated narrative still cited the wrong assertions. That earlier raw response remains failed and preserved. The new checks require both a correct generated ledger and matching narrative evidence; the final source review is bound to the unmodified response hash. This is a targeted regression result, not universal model accuracy or independent security approval. [Latest generated acceptance and full output](REALISTIC_REPOSITORY_REVIEW_20261017.html) · [prior editorial publication](REALISTIC_REPOSITORY_REVIEW_PRIOR_EDITORIAL_20261017.html).

## Prior editorial revision — generated response was not accepted

**Reviewed publication corrected; raw model narrative acceptance NOT passed.** The same frozen 338-block source archive was rerun through the actual DSH agent with a tighter citation contract. It used **993,305 input / 4,236 output tokens** in the cold turn, which still failed quotation/range/length checks. The final response after two same-conversation corrections used **1,001,553 input / 3,108 output tokens** and produced the **1,482-word final report** in **1294.56s**. Literal values: **15/15**; complete answer/source/quotation conditions: **15/15**; narrow narrative ranges: **64/64**. The separate source review's conclusion is: **Raw narrative source acceptance NOT PASSED: two residual assertion/citation misattributions. The published reviewed version corrects these and tightens five further evidence descriptions; raw output remains unchanged.** The original failed-quality result remains preserved below and in the full report.

The cold turn took **1306.54s**, with **0 DSH capacity retries**; the final correction turn separately took **1294.56s**. During admitted work, **20 exact persisted short DSH replies** completed in pairs at **4.03–10.05s**. Model identity and restart count were unchanged. There were **1652 recovering mapping warnings**, so a successful test does not establish generous memory headroom. No shared inference settings or user data changed. Disposable-session archive/hash checks, pod removal and post-cleanup ordinary inference passed.

The workflow fixes canonical values, requested source/definition selection, quotation precision and narrative evidence boundaries. It requires mechanical checks plus a hash-bound source review before task acceptance. These are targeted regression results, not general model accuracy, sustained throughput or independent security approval. [Full revised report and original result](REALISTIC_REPOSITORY_REVIEW_20261017.html) · [citation protocol](REPOSITORY_REVIEW_CITATION_PROTOCOL.md).

## Real repository accuracy and long-output test — 17 October 2026 ICT

**Execution completed; factual retrieval was correct; strict citation/narrative acceptance did not pass.** The actual DSH agent reviewed 239 current source blocks plus 99 labelled historical revisions from DSH/GPU_server, without synthetic filler. It used **992,638 input tokens** and generated **4,767 output tokens**, including a **2,252-word report**. This was DSH agent RPC, not Claude Code, TrueForge or a new manual browser-interface test.

| Result | Recorded outcome |
|---|---|
| Targeted facts | 15/15 intended values correct by independent source review, allowing equivalent units/time formats |
| Original literal checker | 7/15 literal values; 4/15 met every strict answer condition; not relabelled as a pass |
| Quotation and citation limits | 14/15 quotations literally match their cited spans; five exceed 200 characters; two miss requested source/definition-line selection |
| Narrative citations | All 69 ranges exist; 12 exceed the requested 12-line maximum; source review found unsupported/inadequately cited conclusions |
| Latency | 39m39s total: approximately 17m45s before warming, 19m23s preparation, then approximately 2m28s output generation |
| Ordinary DSH during admitted work | 18 correct persisted replies in pairs, 4.03–10.05s; two occurred during report generation |
| Queue behavior | Three DSH-side capacity retries; distinguish these from disabled LiteLLM Router retries |
| Memory | 1,356 recovering mapping warnings in the admitted-phase shared-model log window; no checked fatal signatures or model restart |

The generated report is useful as a draft, not reliable unreviewed guidance. Examples include a changed purported source quotation, a test-comment citation used as proof of an assertion, an incorrectly targeted host-memory citation, and claims about SLA existence/shared resources that exceed the supplied evidence. The report and original answer are retained rather than corrected silently.

The first setup failed on an oversized test-helper exec URI. After runtime deletion, a long slot remained occupied while warming continued; deletion alone did not prove upstream cancellation. The following request waited and retried. The harness now checks admission ownership as well as idle GPU metrics, and uploads helper source instead of putting it in a long command argument. No shared inference configuration changed. The disposable pod was removed after archive/hash readback; post-cleanup inference passed and the admission lock was free.

See the [full accuracy, citation, timing and original-report review](REALISTIC_REPOSITORY_REVIEW_20261017.html), [source narrative](REALISTIC_REPOSITORY_REVIEW_20261017.md), [raw response](context-evidence/realistic-repo-model-response-20261017.json) and [measured phases](context-evidence/realistic-repo-performance-20261017.json). This one task does not establish general million-token analytical accuracy, a sustained-load SLA, two full simultaneous 1M requests or full 8,192-token output acceptance.

## Current-image reacceptance — 16–17 October 2026 ICT

Runtime image: `595452b9d14f79bc5415795145967df713288f49db5f4699db570bcda4c3c5a6`. Existing user histories and workspaces were not used for the capacity tests. The temporary runtime used empty volumes and the same current image, internal inference service and transport configuration.

| Test | Actual result |
|---|---|
| Progressive DSH context | 263,693 input + 8 output; exact persisted reply; 124.28s |
| Progressive DSH context | 519,694 input + 8 output; exact persisted reply; 358.65s |
| Progressive DSH context | 1,007,689 input + 8 output; exact persisted reply; 1173.92s |
| Near-1M tool continuation after gateway fix | 1,008,103 input; 20.16s; real file write/read, content check and marker removal |
| Ordinary DSH during the cold 1M run | 18 exact persisted replies in nine pairs while long work remained active; 4.03–12.04s including polling overhead |
| Busy long-request response after fix | Actual authenticated HTTP 429 after 300.36s under a simulated occupied admission lease; ordinary DSH replies continued |
| Lease release | A subsequent long API request succeeded at 140,034 input tokens |
| Oversized input | HTTP 400 in 1.62s |

The initial real 1M run exposed a separate queueing defect: the internal guard returned 429 after 300 seconds, but LiteLLM's default Router retried rate-limit responses twice and the waiting test client timed out. The original stopped controller record is retained. The 1M response itself was exact and persisted; the queue failure was not reclassified as a pass.

The correction sets `RateLimitErrorRetries: 0` only for `deepseek-v4.1-flash` and `deepseek-flash`. Other error policies and unrelated model groups retain their previous behavior. An installed-Router loopback fixture observed three attempts before the policy and one afterward; an unrelated group still made three. Gateway handovers now use **one replica and Recreate**, preventing overlapping admission processes during rollout. Only the gateway configuration changed; all 20 main runtime specifications and the model pod remained unchanged. Private rollback specifications and the original immutable configuration were retained.

The final 300-second test uses a deliberately held admission lock, not a fabricated GPU workload. It validates the real authenticated gateway's waiting/429 response and lease release. Actual 1M-plus-short-request overlap was established separately by the cold DSH run. The HTTP queue deadline is per request attempt; these measurements are not a client-wide retry or latency SLA.

### Post-fix ordinary concurrency

All **105 exact replies** passed across 15 burst stages and three mixed stages. The interactive controller was interrupted after all 93 burst replies completed; the 12 mixed replies were resumed in a separate record rather than repeating completed bursts.

| Concurrency | Verified burst replies | TTFT p95, s | Completion p95, s | Aggregate output tokens/s |
|---|---|---|---|---|
| 1 | 3 | 0.126 | 3.682 | 31.85–32.30 |
| 2 | 6 | 0.361 | 3.645 | 62.73–65.71 |
| 4 | 12 | 0.393 | 3.867 | 112.94–113.35 |
| 8 | 24 | 0.900 | 5.134 | 162.47–175.69 |
| 16 | 48 | 1.867 | 7.565 | 220.34–232.31 |

The mixed stages used approximately 24K, 96K and 120K inputs. At 120,049 input tokens, the larger request took 35.67s and concurrent short replies took 0.477–0.613s. These are bounded samples, not sustained saturation.

**Memory limitation:** the current-image progressive-test log window contained 1,132 recovering allocator mapping warnings, with a minimum warning-reported free memory of 1.75 MiB. No checked fatal CUDA/OOM, illegal-memory or scheduler-exception signatures were found, and the model pod/restart count stayed unchanged. This is not comfortable memory headroom.

**Qualified operating boundary:** one request above 128K at a time, with ordinary requests remaining concurrent. Two full simultaneous 1M requests, near-1M image inputs, full 8,192-token generation at near-1M input, semantic accuracy across arbitrary million-token material, and sustained-load guarantees are not established. Existing compaction behavior was not requalified by this retest.

[Completion summary](context-evidence/current-image-1m-completion-summary-20261017.json) · [runtime/source readback](context-evidence/current-image-1m-runtime-readback-20261017.json) · [original progressive run and queue failure](context-evidence/dsh-current-image-progressive-context-retest-20261016.json) · [post-fix tool continuation](context-evidence/dsh-current-image-tool-after-admission-fix-20261016.json) · [Router integration fixture](context-evidence/long-admission-retry-router-fixture-20261016.json) · [bounded admission](context-evidence/long-admission-bounded-live-after-fix-retest-20261016.json) · [post-fix bursts](context-evidence/inference-stress-after-admission-fix-20261016.json) · [resumed mixed stages](context-evidence/inference-mixed-after-admission-fix-20261016.json).

## Consolidated stress-test review

**Review date: 17 October 2026 ICT.** The earlier consolidation reconciled retained capacity, concurrency, scheduling and application-level records without another live load test. The later real-repository run above is separate live work. The earlier statement that an isolated candidate was still being tested describes an intermediate stage. The completed current-image results above supersede that status. Separate runs below must not be added together as one uninterrupted benchmark.

### Capacity and memory trials

| Trial | Recorded outcome | Meaning and lesson |
|---|---|---|
| Initial approximately 262K request, static memory 0.92 | CUDA out-of-memory failure; model restarted; approximately 14-minute recovery | Historical incident described in the engineering record; no standalone raw response is bundled. A large KV-slot count did not include temporary attention workspace. |
| 256K startup, static memory 0.88 | Failed before inference | Reducing static allocation too far also prevented the required cache layout from initializing. |
| 250,011-token backend input | Exact `LONG_CONTEXT_OK` | Backend capacity check, not a DSH agent test. |
| 500,012-token backend input, chunk 4,096 | Exact answer, but allocator warnings and low free memory | Rejected as unstable despite the answer. |
| 500,012-token backend input, chunk 2,048 | Exact answer; recorded no scheduler/OOM exception or restart | Intermediate backend qualification; does not transfer automatically to another scheduler. |
| First near-1M backend attempt, chunk 2,048 | Internal Server Error; engineering record reports allocator failures and one restart | Failed trial retained; the response file contains plain error text despite its `.json` name. |
| 1,000,015-token backend input, chunk 1,024 | Exact `LONG_1M_RETEST_OK`, 10 output tokens | Historical backend-only success; not proof of full output capacity or DSH end-to-end operation. |
| Two 480,012-token backend requests submitted together | Both exact, 538.22s; kernel-loading warning with negligible transient headroom | Two submissions completed; this is not two full 1M contexts or proof of continuous parallel execution. Current gateway admits only one request above 128K. |
| Current-image DSH progressive 263,693 → 519,694 → 1,007,689 input | Exact persisted replies; 124.28 → 358.65 → 1,173.92s | Actual DSH/tools envelope through LiteLLM; the accompanying queue-control failure remains recorded separately. |

Sources: [context/memory trial narrative](CONTEXT_OPTIMIZATION_20261015.md), [256K response](context-evidence/near-256k-response.json), [512K at chunk 4,096](context-evidence/near-512k-response.json), [512K at chunk 2,048](context-evidence/near-512k-response-chunk2048.json), [failed 1M response](context-evidence/near-1m-response.json), [successful backend 1M](context-evidence/near-1m-response-chunk1024.json), [dual 480K](context-evidence/dual-480k-response.json), [current-image progressive record](context-evidence/dsh-current-image-progressive-context-retest-20261016.json). Warning/restart details for early trials come from the engineering narrative, not the response bodies alone. Its 128K and pending-retest statements are historical checkpoints, superseded by this guide's current-image section.

### Scheduling and real-user responsiveness trials

| Trial | Result under contention | Correction or interpretation |
|---|---|---|
| Original scheduler, 133,044-token long input | Four short replies took 32.38–33.58s; none finished before the long reply | Reproduced head-of-line blocking. Post-test fast replies had previously hidden this problem. |
| V1, tiny/fresh short requests | All four finished before the long reply; approximately 0.58–1.45s across the two patterns | Partial improvement only. |
| V1, continuing sessions with approximately 24K cached history | Four short replies still took 33.01–34.07s | Failed cached-session gate; corrected prefix classification in V2. |
| V2, continuing cached sessions and fresh small requests | All eight short replies finished before their respective long request; 0.59–1.47s | Bounded approximately 133K mixed-load acceptance, not a 1M result. |
| First isolated 1M-candidate escalation | 256,046-token leg passed; subsequent approximately 512K leg returned HTTP 500 | Failed escalation preserved; led to V3 single-chunk-owner correction. |
| V3, 512,047-token API input | Exact in 378.31s; tiny short probes 0.62–0.90s | API-only success still missed the real DSH system/tool-prefix workload. |
| Actual ordinary DSH during uninterrupted 512K prefill | Exact eventual reply after approximately 368.7s, with timeout/retry | Failed responsiveness gate; a tiny API probe was not representative of DSH. |
| Incremental proxy warming and final-wire normalization | Warmed 256K/500K agent and tool trials, then actual near-1M DSH qualification | Prepare prefixes in bounded extensions and count the final tools/template envelope. Hot-cache follow-ups are distinct from cold input throughput. |
| Current-image cold near-1M plus ordinary DSH | 18 exact persisted replies in nine pairs; 4.03–12.04s | Actual overlap, but the slowest reply exceeds the earlier five-second small-probe target. No universal sub-five-second promise. |
| Current-image API bursts during cold near-1M | Two concurrent: 9.00s, 26.46 aggregate output tokens/s; four: 10.38s, 45.85 aggregate output tokens/s | Confirmed overlap; substantially slower than idle short-burst throughput. |

Sources: [scheduler comparison and failed V1 gate](SCHEDULING_FAIRNESS_20261015.md), [candidate escalation](context-evidence/current-1m-canary-20261016.json), [V3 512K](context-evidence/current-1m-v3-512k-20261016.json), [actual DSH starvation](context-evidence/dsh-1m-agent-during-512k-20261016.json), [warmed 256K agent](context-evidence/dsh-agent-during-warmed-256k-20261016.json), [warmed 500K agent](context-evidence/dsh-image-agent-during-warmed-500k-20261016.json), [warmed 500K tools](context-evidence/dsh-image-tool-during-warmed-500k-20261016.json), [final-wire token comparison](context-evidence/final-wire-token-id-comparison-20261016.json), [current mixed-load details](context-evidence/dsh-current-image-progressive-context-retest-20261016.json).

### Burst, admission and reliability coverage

Four retained ordinary-load campaigns cover 1/2/4/8/16 concurrent bursts and approximately 24K/96K/120K mixed input. Each campaign accounts for 105 exact replies across 18 stages; these are separate repetitions, not 420 simultaneous requests or a prolonged saturation test:

| Campaign | Scope and record status |
|---|---|
| Earlier 128K product baseline | Completed 105/105; [baseline tables and limits](LLM_128K_BASELINE_BEFORE_1M_20261016.md), [raw record](context-evidence/inference-stress-20261016-live.json). |
| Earlier deployed 1M proxy | Completed 105/105 within short/mixed input sizes; [raw record](context-evidence/inference-stress-1m-final-route-20261016.json). Raising the ceiling did not make these million-token requests. |
| Current-image, before admission retry correction | Completed 105/105; [raw record](context-evidence/inference-stress-current-image-retest-20261016.json). Separate from the progressive controller that stopped on queue timeout. |
| Current-image, after admission retry correction | 93 burst replies completed before controller interruption, then 12 mixed replies resumed and completed; combined 105/105. Both records and the table above preserve that split. |

The queue tests found a real failure: two hidden Router retries extended a nominal 300-second admission wait beyond the client's timeout. After the targeted retry correction, an installed-Router fixture verified one attempt for each guarded alias and three for an unrelated group. A deliberately held admission lease then produced a real authenticated 429 at 300.36s; short DSH requests continued, lease release allowed a 140,034-token request, and overflow returned 400. This verifies admission behavior, not two actual near-1M GPU requests. The external 429 did not include a `Retry-After` header.

Transport, tool continuation, compaction and restart/persistence checks are described in their dedicated sections below. The 315-second delayed endpoint is a transport fixture, the low-threshold compaction run is a functional fixture, and the Router loopback endpoint is a retry fixture. None should be counted as a GPU stress benchmark.

**Remaining coverage limits:** no sustained soak/saturation test, two full concurrent 1M requests, full 8,192-token output near maximum input, near-1M vision, arbitrary long-document recall/semantic-quality assessment beyond the declared tasks. Recovering allocation warnings remain material. Short-request responsiveness is measured, not guaranteed. A further live test must save a new record and identify the exact runtime, route and scheduler rather than inheriting an older pass.

## Architecture and limits

`Authenticated user → private DSH → authenticated internal LiteLLM :4000 → loopback context guard :4001 → SGLang :8000 → shared four H100 GPUs`

| Layer | Deployed policy |
|---|---|
| DSH runtime | `0.2.0-rc.2`; current managed-tools image digest `595452b9d14f79bc5415795145967df713288f49db5f4699db570bcda4c3c5a6`; the latest reacceptance above used this current image; the earlier qualification used `87bc12dd5c2419e640c11358881f01709944a259498cf38a699fcc57d037e1a3` |
| DSH DeepSeek aliases | 1,048,576 total context; maximum output 8,192 |
| DSH transport | Provider timeout and stream-idle settings 3,600,000 ms; effective transport acceptance tested separately |
| LiteLLM | Pinned digest `4870893763aca143f590bd5685a25219037af027d1d27e97abcb17ac9ec5d09f`; existing inference keys and Secret references preserved |
| Final request budget | Exact backend tokenizer includes messages, tools and template options; input + output + 256 reserve must fit 1,048,576 |
| Long-request admission | One request above 128K at a time in one gateway replica; one FIFO waiting position up to 1,500 seconds; excess waiters refused immediately; no Router rate-limit retries for the two guarded model groups |
| Ordinary requests | Bypass the long-request lease and remain concurrent; queueing and slower output remain possible |
| SGLang | Image digest `4a5d132a06a77c8331e15845f2e925adc788b00105097ad55409afa3f4fa4860`; model snapshot `dba1be0a40aa45a94ad051997016db3960a90277` |
| Backend scheduling | Context 1M, static memory 0.90, running cap 16, chunk 1,024, maximum prefill 2,048, decode interval four, V2 fairness + V3 single-chunk-owner guard |
| Measured cache pool | 1,179,648 token slots; one near-1M request plus smaller work, not two complete 1M contexts |
| Automatic compaction | Ratio 0.875, headroom 65,536, summary output 8,192; normal trigger 917,504 estimated tokens |

One million is **total request capacity**, not one million input plus unlimited output. With the full 8,192 output allowance, counted input must not exceed 1,040,128 after the proxy reserve. A smaller output reservation permits larger input. Near-1M text requests with DSH tool schemas and an actual write/read tool continuation are qualified for the recorded cases. Image requests above 128K are explicitly rejected because token-only prefix warming cannot reproduce image embeddings. Near-1M vision, full 8,192-token generation at near-1M input, and every possible plugin/tool result are not established.

## Final-payload alignment review — 17 October 2026 ICT

The original failure was a prompt mismatch, not insufficient warming: an earlier tool request counted 7,689 tokens but inference processed 7,561. The backend tokenizer materialized an omitted function `strict` default differently from chat inference. Warming the former token sequence could not guarantee a reusable prefix for the latter. The retained [before/after comparison](context-evidence/tool-default-exact-ids-and-cache-20261016.json) shows that explicit normalization made all prompt IDs identical.

The deployed correction is already at the final forwarding boundary after LiteLLM: normalize prompt-affecting defaults, tokenize the complete final messages/tools/template settings, warm those returned IDs, and forward the same normalized conditioning. Only output-budget, request-ID and streaming transport fields are subsequently adjusted. Explicit caller values are preserved. Cache loss or a failed handoff stops the request rather than silently attempting the entire cold prompt.

Fresh review read back all three installed source hashes and matched them to this repository. A small synthetic tool-schema request through the installed normalization/tokenizer and backend chat path counted **258 tokens**, used **258 input tokens**, returned the exact requested answer, and exposed **identical prompt token IDs**. This is a fresh alignment check, not another near-1M capacity test or a complete authenticated DSH replay. The recorded current-image end-to-end long tests remain the capacity evidence.

All **nine forwarder regression tests** passed. New coverage compares counted conditioning with forwarded conditioning (messages, tools, tool choice, reasoning, template settings and continuation), verifies the exact returned IDs reach warming, and checks explicit defaults are preserved. Existing cases cover cache-handoff failure, cancellation/lease cleanup, non-streaming conversion, multimodal rejection and unavailable token budgeting. These are isolated regression tests, distinct from the live token comparison. [Fresh source/alignment readback](context-evidence/final-wire-review-20261017.json).

## Keeping ordinary requests responsive

Small prefill chunks avoid the temporary attention-memory failure seen in the older 262K experiment. V3 also prevents two requests from owning the scheduler's single chunk slot, which caused the first V2 512K assertion.

That was insufficient for actual DSH: its roughly 7.5K system/tool prefix exceeds V2's interactive lane. A real short DSH request waited 368.7 seconds during uninterrupted 512K prefill while tiny API probes were fast. The final proxy prepares long prefixes in 2,048-token extensions and yields between them. Intermediate one-token outputs are discarded; they never become tool actions or conversation messages. Cache reuse is checked, and loss stops preparation instead of falling back to one blocking prefill.

A bounded two-second cache probe can reuse a continuing conversation's prefix immediately. On a cold miss, the proxy aborts its own probe and prepares incrementally. Each request has its own ID; cleanup aborts only owned work and releases the admission lease. The guard listens only on loopback; production request-body capture is disabled.

## Earlier qualification tests

| Test | Observed result | Scope |
|---|---|---|
| DSH 257,684 input tokens | Exact answer, 108.26 seconds, persisted prompt matched | Actual agent with tool schemas |
| Follow-up in that 257K conversation | 257,738 input, exact answer, 2.04 seconds | Hot-prefix reuse, not cold throughput |
| Final cold DSH near 1M | 1,007,689 input + 8 output, 1,170.08 seconds, exact/persisted, zero retries, no model restart | Recovering GPU allocation warnings recorded |
| Tool follow-up in the same near-1M conversation | 1,008,103 input + 8 output; 20.16s; real write/read and file verification/removal | Zero retries; same model pod |
| Two ordinary DSH calls during near 1M | 4.03 / 6.04 seconds, exact and persisted | Actual DSH calls, not tiny API-only probes |
| Tool execution | Canary 8.04s; actual private admin after transport rollout 38.12s during near-1M load; file content/hash checked and marker removed | Real tool calls; synthetic files only |
| Non-streaming proxy | 140,018 input + 4 output, exact answer, 44.99 seconds | Internal stream assembled into JSON |
| Endpoint override | HTTP 401; LiteLLM authentication rejected client `api_base` | Observed rejection; not misattributed to custom hook |
| Automatic compaction | Persisted summary, retained verification code and correct recall | Disposable 1M profile with lowered 0.02 trigger; production trigger unchanged |
| Rollout regression checks | Composed owner/admin policies, private login/history denials, non-root terminal WebSockets, original file hashes | Main deployment; excludes legacy DSH2/DSH3 |

During the production-route near-1M follow-up, two ordinary DSH calls returned in **4.03 / 4.04 seconds**. Two concurrent API replies produced **16.01 aggregate output tokens/sec** in 14.86 seconds; four produced **27.10 aggregate tokens/sec** in 17.56 seconds. All outputs matched and model pod/restart state stayed unchanged. Long-load output was slower: responsiveness for a brief answer does not mean unchanged sustained output speed.

Evidence: [near 1M](context-evidence/dsh-final-wire-near-1m-20261016.json), [hot continuation](context-evidence/dsh-final-wire-250k-continuation-20261016.json), [tools](context-evidence/final-wire-tool-acceptance-20261016.json), [non-streaming/rejection](context-evidence/final-wire-api-acceptance-20261016.json), [compaction fixture](context-evidence/dsh-automatic-compaction-fixture-20261016.json), [production mixed traffic](context-evidence/production-1m-mixed-concurrency-20261016.json).

The later **final managed-transport run** measured two ordinary DSH replies at **6.04 / 8.04 seconds**, with the long test still active before and after. Its two-request API burst produced **8.98 aggregate output tokens/sec** in 22.15 seconds; four produced **15.51 aggregate tokens/sec** in 25.65 seconds. This is slower than the earlier mixed sample above. Different prefill progress and load can change the rate; no fixed latency or output-speed guarantee follows from either sample. [Final managed mixed-load record](context-evidence/final-managed-mixed-1m-20261016.json).

### Earlier stress sample on the deployed 1M proxy

**105/105 exact replies passed across 18 stages.** These bursts use short requests; a 1M ceiling does not make every request a 1M workload. Times include queue, prefill and networking. Percentiles come from small samples and are not an SLA.

| Concurrent requests | Replies verified | TTFT p95, seconds | Completion p95, seconds | Effective output tokens/sec per request | Aggregate output tokens/sec |
|---|---|---|---|---|---|
| 1 | 3 | 0.128 | 3.684 | 31.84–32.30 | 31.83–32.29 |
| 2 | 6 | 0.355 | 3.622 | 31.59–34.30 | 55.91–65.70 |
| 4 | 12 | 0.372 | 3.884 | 29.53–32.15 | 92.38–113.58 |
| 8 | 24 | 0.912 | 5.132 | 21.47–25.92 | 167.84–177.70 |
| 16 | 48 | 2.143 | 7.655 | 12.68–18.22 | 208.88–240.25 |

Fresh mixed requests used 24,044, 96,049 and 120,048 input tokens. All nine short probes completed before their larger request. At 120,048 input, the larger answer took **35.91 seconds** and short replies took **0.486–0.641 seconds**. Model identity/restart counts stayed unchanged; checked CUDA OOM, illegal-memory and scheduler-exception signature counts were zero. These are bounded samples, not sustained saturation or 16 simultaneous near-1M acceptance.

[Full actual responses/samples](context-evidence/inference-stress-1m-final-route-20261016.json) · [recalculated tables](context-evidence/inference-stress-1m-final-summary-20261016.json). The [older 128K baseline](LLM_128K_BASELINE_BEFORE_1M_20261016.md) is retained separately.

## Five-minute timeout investigation and fix

The first near-1M successes required automatic retries at approximately 300 seconds despite the DSH provider's one-hour settings. A delayed synthetic endpoint reproduced that boundary. The installed Undici client source defaults header/body waits to 300 seconds when no explicit transport timeout is supplied. SDK/provider timeouts alone did not establish the effective HTTP deadline.

A small Node dispatcher override now supplies one-hour header/body waits **only for the operator-managed internal inference origin**. Other origins, abort signals and dispatch behavior are unchanged. The live runtime uses a read-only, content-addressed ConfigMap; the future image startup script includes the same hook. The controlled **315-second delayed-response retest passed in 316.59 seconds with zero retries**, through actual DSH and LiteLLM, without using the model. This is transport evidence, not a fake inference benchmark. The final actual cold near-1M test also completed with zero retries; its warnings and timing are recorded above.

The rollout also corrected a restart hazard in the profile-backup initializer: it now verifies and reuses the retained original backup on later starts instead of refusing an existing directory or overwriting the rollback copy. Actual replacement of all 20 runtimes checked the loaded hook hash and preserved **40 workspace/attachment markers**. No data mount, permission or owner mapping was replaced.

[Before-fix transport observation](context-evidence/dsh-five-minute-transport-before-fix-20261016.json) · [315-second acceptance](context-evidence/dsh-five-minute-transport-managed-fixture-20261016.json) · [20-runtime transport/persistence rollout](context-evidence/1m-managed-transport-rollout-20261016.json).

## Compaction

```text
threshold = floor(min(context × ratio, context − reserved output − headroom))
          = min(1048576 × 0.875, 1048576 − 8192 − 65536)
          = 917504 estimated tokens
```

Checks happen between agent steps. Pressure is estimated, unlike the proxy's exact count. A large single input/tool result may reach the request guard before auto compaction; overflow is refused. The lowered-threshold fixture verified the real plugin's summary persistence and recall, not every historical session or complete detail preservation after a near-1M summary. Manual `/compact` requires a useful compactable range.

## Setup and controlled rollout

1. Model/overlay source: Azure `GPU_server/deployment/vllm/`. DSH/proxy: its `dsh-environments/` mirror or GitHub `dsh_setup`. Retain pinned images, reviewed hashes and existing Secret references. Do not apply legacy LiteLLM placeholder Secrets or bootstrap shared-pool YAML over private Production.
2. Build/test the runtime in Azure pipeline 1315. Initial 1M build **62773**, source `c20b31078b84604a6d1c19bfbdd59be166ff27ae`, produced the image used for the near-1M acceptance. The subsequent managed-tools rollout uses build **62790**, source `52bf535850c5d5c3991ebcdb3aeece776785803e`, while preserving all 20 numerical DSH 1M profiles and the model pod. The 17 October operator policy overlay now defaults Claude to 1M and sets one-hour model deadlines; actual Claude/TrueForge capacity cases and current runtime readback are recorded above. The running image is unchanged, so pin the policy overlay with it rather than inferring effective settings from the image alone. See [managed tools](MANAGED_CLAUDE_AND_TRUEFORGE.md). Later documentation builds do not change the live image automatically.
3. Prepare isolated synthetic storage with `scripts/prepare_1m_canary.py`; qualify actual tokenizer IDs, streaming, tools, cache handoff, compaction and mixed traffic. Synthetic envelope capture must stay off in Production.
4. Run `scripts/promote_1m_proxy.py` in plan mode, then `--apply` with passed actual near-1M acceptance and a fresh private rollback directory. It preserves auth/database references and unrelated routes, creates immutable configuration and adds the loopback guard. Test actual inference and rejected endpoint override after replacement.
5. Run `scripts/promote_1m_runtimes.py` in plan mode, then `--apply` with another fresh private rollback directory. It selects existing main private runtimes, requires Recreate/single-writer behavior, preserves mounts and backs up the old profile **inside each private PVC** before changing it. Read back imageIDs, numerical policies and effective owner/admin compositions.
6. For the pinned runtime used here, apply `scripts/rollout_managed_transport.py` with the passed delayed-response acceptance and a fresh private rollback directory. This adds the read-only internal-origin transport hook and repairs repeat-start backup handling. Future qualified images also preload the hook from their startup script; compare actual source hashes before changing overlays.
7. Recheck login/logout, real terminal execution, peer-history denial, workspace markers and original session hashes; update the admin snapshot and English report from actual results. Never replace DA_WORKSPACE or reassign histories as part of a context upgrade.

## Rollback and limits

Restore each old profile before starting its previous image; reverting only the image can leave an unsafe mismatched 1M profile. The controller prepares a restore init step and checks the retained backup hash. Restore the previous LiteLLM Deployment to recover its original immutable configuration. These CPU-side reversions do not require a GPU restart. Prior model/overlay snapshots remain available separately.

Preserve newer workspace/history writes; rollback does not overwrite them with older data. User/environment routes, CIFS mounts and ownership are unchanged. Datalake authorization, remote Spark egress, legacy-instance migration and device/browser controls remain separate security boundaries. Raising context does not close those risks.
