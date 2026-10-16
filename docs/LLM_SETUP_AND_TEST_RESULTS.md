# Shared LLM — 1M Setup, Performance and Operational Limits

## Current answer

The main **DSH → LiteLLM → SGLang** route supports **1,048,576 total tokens**, with an 8,192 output ceiling and a 256-token reserve. All 20 main DSH runtime profiles were read back, and the current managed-tools image was qualified using a temporary DSH runtime with isolated synthetic storage against the Production inference service.

The earlier clean current-image cold DSH capacity request used **1,007,689 input + 8 output tokens**, returned the exact persisted answer in **1,173.92 seconds (19m34s)**, while 18 ordinary DSH replies completed in pairs during the long run. After the gateway retry correction, a real write/read tool continuation used **1,008,103 input tokens** and passed in **20.16 seconds**. This qualifies the recorded main DSH cases, not the separate Claude Code or TrueForge clients.

The earlier 128K statements described an incomplete deployment: the backend had been raised while DSH/LiteLLM guardrails remained lower. The [earlier review](LLM_128K_BASELINE_BEFORE_1M_20261016.md) and failed/intermediate trials are retained. Initial near-1M successes took about 19 minutes and required three automatic timeout retries. The final scoped Node transport correction removed those retries in both the delayed fixture and the real cold test.

**Earlier qualification memory evidence:** the preceding-image cold run recorded **1,460 recovering allocator mapping warnings**, with a minimum warning-reported free memory of **9.75 MiB** while attempting a 20 MiB mapping. No checked fatal exception or model restart occurred; ordinary DSH inference still returned correctly after warnings appeared. This passing test does not establish comfortable memory headroom, unrestricted long concurrency or a service-level guarantee. [Final cold acceptance and warning summary](context-evidence/final-managed-1m-acceptance-summary-20261016.json) · [near-1M tool continuation](context-evidence/final-managed-1m-tool-continuation-20261016.json).

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

**Remaining coverage limits:** no sustained soak/saturation test, two full concurrent 1M requests, full 8,192-token output near maximum input, near-1M vision, near-1M Claude Code/TrueForge run, or arbitrary long-document recall/semantic-quality assessment. Recovering allocation warnings remain material. Short-request responsiveness is measured, not guaranteed. A further live test must save a new record and identify the exact runtime, route and scheduler rather than inheriting an older pass.

## Architecture and limits

`Authenticated user → private DSH → authenticated internal LiteLLM :4000 → loopback context guard :4001 → SGLang :8000 → shared four H100 GPUs`

| Layer | Deployed policy |
|---|---|
| DSH runtime | `0.2.0-rc.2`; current managed-tools image digest `595452b9d14f79bc5415795145967df713288f49db5f4699db570bcda4c3c5a6`; the latest reacceptance above used this current image; the earlier qualification used `87bc12dd5c2419e640c11358881f01709944a259498cf38a699fcc57d037e1a3` |
| DSH DeepSeek aliases | 1,048,576 total context; maximum output 8,192 |
| DSH transport | Provider timeout and stream-idle settings 3,600,000 ms; effective transport acceptance tested separately |
| LiteLLM | Pinned digest `4870893763aca143f590bd5685a25219037af027d1d27e97abcb17ac9ec5d09f`; existing inference keys and Secret references preserved |
| Final request budget | Exact backend tokenizer includes messages, tools and template options; input + output + 256 reserve must fit 1,048,576 |
| Long-request admission | One request above 128K at a time in one gateway replica; wait up to 300 seconds, then retryable 429; no Router rate-limit retries for the two guarded model groups |
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
2. Build/test the runtime in Azure pipeline 1315. Initial 1M build **62773**, source `c20b31078b84604a6d1c19bfbdd59be166ff27ae`, produced the image used for the near-1M acceptance. The subsequent managed-tools rollout uses build **62790**, source `52bf535850c5d5c3991ebcdb3aeece776785803e`, while preserving all 20 numerical DSH 1M profiles and the model pod. The new Claude client defaults to 200K; its explicit 1M selection passed a short call. Neither that selection nor TrueForge 1M metadata is a near-1M client test. See [managed tools](MANAGED_CLAUDE_AND_TRUEFORGE.md). Later documentation builds do not change the live image automatically.
3. Prepare isolated synthetic storage with `scripts/prepare_1m_canary.py`; qualify actual tokenizer IDs, streaming, tools, cache handoff, compaction and mixed traffic. Synthetic envelope capture must stay off in Production.
4. Run `scripts/promote_1m_proxy.py` in plan mode, then `--apply` with passed actual near-1M acceptance and a fresh private rollback directory. It preserves auth/database references and unrelated routes, creates immutable configuration and adds the loopback guard. Test actual inference and rejected endpoint override after replacement.
5. Run `scripts/promote_1m_runtimes.py` in plan mode, then `--apply` with another fresh private rollback directory. It selects existing main private runtimes, requires Recreate/single-writer behavior, preserves mounts and backs up the old profile **inside each private PVC** before changing it. Read back imageIDs, numerical policies and effective owner/admin compositions.
6. For the pinned runtime used here, apply `scripts/rollout_managed_transport.py` with the passed delayed-response acceptance and a fresh private rollback directory. This adds the read-only internal-origin transport hook and repairs repeat-start backup handling. Future qualified images also preload the hook from their startup script; compare actual source hashes before changing overlays.
7. Recheck login/logout, real terminal execution, peer-history denial, workspace markers and original session hashes; update the admin snapshot and English report from actual results. Never replace DA_WORKSPACE or reassign histories as part of a context upgrade.

## Rollback and limits

Restore each old profile before starting its previous image; reverting only the image can leave an unsafe mismatched 1M profile. The controller prepares a restore init step and checks the retained backup hash. Restore the previous LiteLLM Deployment to recover its original immutable configuration. These CPU-side reversions do not require a GPU restart. Prior model/overlay snapshots remain available separately.

Preserve newer workspace/history writes; rollback does not overwrite them with older data. User/environment routes, CIFS mounts and ownership are unchanged. Datalake authorization, remote Spark egress, legacy-instance migration and device/browser controls remain separate security boundaries. Raising context does not close those risks.
