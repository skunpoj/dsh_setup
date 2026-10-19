# DSH performance optimization on the existing four GPUs

## Current qualified DSpark profile, 19 October 2026

**Current qualified DSpark profile, 19 October 2026:** actual DSH processed **1,007,752 input / 431 output tokens** with the complete correct saved answer in **22m22.2s**. **46/46 ordinary replies** passed during long preparation (**3.56–11.21s**, paired median **5.08s**), including two eight-client bursts. The qualifying model generation had **zero retries, allocator warnings or unexpected restarts**. Three 599-token structured short answers streamed at **164.60–166.11 tokens/sec per conversation**. Explanatory prose samples measured **76.76–96.76 tokens/sec**. One expensive request is admitted at a time; up to **eight** requests run actively, with additional ordinary clients queued. [Results and setup](DSH_PLATFORM_GUIDE.html#guide-section-10).

| Setting | Qualified value |
|---|---|
| Total context | 1,048,576 tokens across main DSH, LiteLLM and SGLang |
| Model / GPUs | DeepSeek-V4.1-Flash, tensor parallel 4, existing node |
| Recorded GPU memory | Four H100 NVL devices reporting 95,830 MiB each |
| Speculative decoding | DSpark, block size 5 |
| Static memory | 0.923 |
| Active requests / CUDA graph cap | 8 / 8 |
| Prefill chunk / batch budget | 1,024 / 1,024 tokens; two prefill requests; separate prefill/decode |
| Prefix tails / decode interval | 16 / 4 |
| Full / sliding-window cache slots | 1,150,976 / 17,920 |
| Attention-score temporary tile | 256 MiB |
| Preparation step | 2,048 tokens at the final forwarding boundary |
| Long admission | One active request above 128K; one FIFO waiter, at most 1,500s; further long requests receive 429 |
| Output budget | At most 8,192 tokens plus a 256-token safety reserve |

| Actual DSH check | Measured result |
|---|---|
| Focused 256K stage | 257,691 input; exact seven-token answer in 130.57s; eight correct short replies, median 3.56s |
| Recorded near-1M known-answer task | 1,007,752 input / 431 output; **22m22.2s**; exact and saved |
| Near-1M answer stream | **147.82 tokens/sec** |
| Ordinary replies during long work | **46/46** exact, saved and retry-free; **3.56–11.21s** |
| Ordinary paired median | **5.08s** |
| Eight-client cohorts during long work | Two completed cohorts at prepared prefixes above 600K and 900K |
| Structured short answers | Three outputs of 599 tokens; **164.60–166.11 streaming tokens/sec each** |
| Natural-language samples | First: 406 tokens at 76.76 tokens/sec; factual correction: 350 tokens at **96.76 tokens/sec**, final content reviewed |
| Cached near-1M continuation | 1,008,209 input / 1,199 output; **14.86s**; **158.32 streaming tokens/sec** |
| Actual near-1M tool continuation | 1,009,673 input; **13.42s**; actual file create/read/delete checked |
| Short client bursts after capacity run | **31/31** exact saved replies across 1, 2, 4, 8 and 16 clients; active GPU cap stays eight |
| Full near-1M qualification failures | **0 retries / 0 allocator warnings / 0 unexpected restarts** |
| Existing history preservation | **167 histories / 188 files across 20 runtimes** retained IDs and bytes |

These fresh client bursts ran after the identical-profile handover. The GPU admits at most eight active requests; a 16-client burst queues additional requests.

| Clients | Correct replies | Elapsed per reply | Stream tokens/sec per conversation | Combined tokens/sec over full cohort |
|---:|---:|---|---|---:|
| 1 | 1/1 | 1.29–1.29s | 169.05–169.05 | 92.35 |
| 2 | 2/2 | 2.59–2.84s | 70.96–138.66 | 83.76 |
| 4 | 4/4 | 2.87–3.88s | 54.86–102.88 | 122.43 |
| 8 | 8/8 | 3.20–5.98s | 49.89–99.33 | 158.45 |
| 16 | 16/16 | 3.11–11.21s | 47.91–104.15 | 169.01 |

Combined throughput includes the cohort request window and is not the rate of a single conversation.

[Sanitized numeric measurements](context-evidence/dspark-qualification-20261019.json).

### How the optimization works

DSpark predicts several candidate tokens using its draft path and checks them with the target model. It speeds accepted output without reducing the context ceiling. The memory changes target separate peaks: owned attention-score buffers are reused for ReLU and weighting, score computation uses smaller tiles, and FP4 dequantization avoids expanded scales and oversized integer lookup indices. Reducing the active-request and graph caps to eight releases persistent graph memory while preserving ordinary parallel service.

The startup gate compares the original and patched calculations on the actual GPUs before the model starts: 80 score cases, eight tiled cases, 132 FP4 cases and eight FP4 memory checks passed. Isolated large-score peak memory fell from 1,088 to 272 MiB; isolated FP4 peak memory fell from 1,280 to 584 MiB. These peaks occur in different operations and must not be added together as a global memory saving. Source hashes fence the pinned runtime; changed upstream targets stop initialization. Qualification helpers reject optimized Python modes that would disable their assertions.

The shared final-payload guard still admits one expensive request and one bounded FIFO waiter. Ordinary work bypasses that long queue. Eight is the actively running GPU cap, not a total user limit: a 16-client burst queues and completes. Two full-1M requests are not admitted simultaneously. Central workspaces, credentials and history mounts are unchanged by the GPU rollout.

### How to read the results

Preparing a million-token input remains expensive. The earlier cold reference took **24m36s**; this run took **22m22.2s**, with a different known-answer payload and traffic schedule. This is a measured comparison, not a controlled percentage improvement. The successful cached continuation reuses prepared context and is not a cold preparation result. Larger 8,192-token warm steps previously lost prefix reuse under diverse traffic, so the qualified default remains 2,048.

Streaming rate is `(output tokens − 1) / first-to-last-text seconds`; whole-turn time includes preparation, queueing and DSH delivery. The three 599-token structured answers exceed 100 streaming tokens/sec; natural prose and a near-1M answer have their own rates above. This does not promise 100+ for every conversation or concurrent load. The known-answer task checks three references distributed through the input and the complete requested number sequence; it does not establish general million-token analytical quality. Fresh tests here use actual native DSH session APIs through the shared gateway, not a fresh Claude Code, TrueForge or browser-login acceptance.

One-second NVML samples through the full near-1M capacity run observed a minimum **38 MiB free per GPU**. Follow-ups are not covered by that sample. Sampling does not bound shorter allocation peaks. GPU headroom remains limited, so the matched full-context, short-traffic and tool tests—not nominal cache slots—qualify this profile.

### Bootstrap and persistence verification

The full near-1M, cached-output and tool results were recorded before an operator-channel recovery. The same qualified GPU specification was then redeployed with all four runtime-module hashes unchanged. The current generation reran GPU reference gates, three real DSH structured replies, 31 concurrent-client replies and a natural-language sample. The full cold near-1M test was not repeated solely for this identical-profile handover.

The deployed bootstrap refuses optimized Python modes before optional imports so qualification assertions remain active. GPU reference gates run before startup and generated source hashes are read back independently. Workspace mounts remain unchanged, and the saved 1M specification is retained for rollback.

### Review of the generated explanation

The initial 406-token prose response streamed at **76.76 tokens/sec**, but overstated what the tile budget guarantees and blurred admission errors with memory handling. Its raw response and failed content review remain preserved. A correction requested inside the same DSH conversation returned a 350-token explanation at **96.76 tokens/sec**. That actual DSH output accurately distinguishes input preparation, speculative output decoding, the limited attention-score tile budget, other GPU allocations and the bounded admission queue. The stored model response was not edited. These two different turns are language-generation samples, not a controlled speed comparison or a promise of 100 tokens/sec for prose.

## Earlier trial record — 18–19 October

The following record retains the failed candidates and the then-restored profile. The operating profile is the DSpark profile above.

### Why the final headroom change was needed

The first 256 MiB tile attempt stopped after startup because a Windows CRLF expected hash differed from the generated Linux LF file. No DSH inference was accepted in that attempt; it was a verification defect, not another GPU memory failure. Byte-normalized generation and an exact Linux CLI preflight corrected it.

The corrected 256 MiB/cap-16 profile passed the focused 257K test, then failed in FP4 dequantization during near-1M preparation: it requested 194 MiB with 183.75 MiB free and restarted once. The owned disposable test was cancelled, and the saved 1M profile was restored with actual DSH verification. The FP4 buffer changes therefore address a different peak from the earlier attention-score failure.

With the FP4 changes and active/graph caps reduced to eight, the 0.925 trial returned the complete exact answer for **1,007,752 input / 431 output tokens in 22m23.3s**, streaming at **148.12 tokens/sec**. All **46 overlapping short replies** passed, including both eight-client bursts; the paired median was **5.07s**, with zero retries or unexpected restart. The strict gate still failed: five recoverable mapping attempts across four GPU ranks produced **20 warning lines**, requesting 20 MiB when 3.75–17.75 MiB remained free. The raw failed status is retained. The automatic controller restored the saved profile rather than relabel this as a zero-warning pass.

The final candidate reduces static allocation from **0.925 to 0.923**, reserving roughly 190 MiB more per GPU for temporary work. It keeps the context ceiling, eight active slots, DSpark block size and generated runtime math unchanged. Its separate full qualification is reported above. The measured planner uses 1,670.75 bytes per full-cache token; the actual post-start pool sizes, rather than a projected capacity, are published in the current profile table.

### Operator transport failure and corrected delivery harness

After the clean full near-1M, cached output and tool tests, the 16-client stage lost parallel Windows Kubernetes exec WebSocket channels. The raw operator harness failed and triggered a conservative recovery. Independent readback recovered **all 16 complete native DSH records**, each exact, saved and retry-free; no owned running turn was cancelled and the model log contained zero allocator-warning or fatal signatures. The raw failed result is preserved separately from this functional reconciliation.

The same qualified DSpark specification was redeployed with unchanged runtime source hashes. The corrected harness carries concurrent native DSH clients through **one** operator channel. Its fresh 31 replies across 1, 2, 4, 8 and 16 clients passed after the handover. An operator-channel exit code alone must not be treated as a model regression: inspect saved native answers and actual model health first. A confirmed wrong answer, model failure or restart remains a rollback trigger. The probe itself never deploys or restarts a workload.

Run the probe only against an operator-created disposable DSH canary. It checks the expected app identity and refuses persistent or host-mounted storage:

```sh
python scripts/probe_dsh_concurrency.py --namespace "$APP_NAMESPACE" --pod "$DISPOSABLE_DSH_POD" --expected-app "$DISPOSABLE_DSH_APP" --host "$DSH_HOST" --output "$PRIVATE_RESULT_JSON"
```


### Recovery before the current qualification

The original **1,048,576-token model profile and 2,048-token preparation steps** are restored. The full recovery DSH turn returned the complete known answer for **1,007,752 input / 431 output tokens** in **24m43.7s**, with **zero retries, no allocator warnings and no model restart**. Its answer streamed at **32.99 output tokens/sec**. The preset output-length check required more than 500 tokens; the compact correct answer used 431, so that check remains failed and is preserved in the raw result. **42/42** paired short replies were exact, persisted and retry-free, taking **6.07–10.60s** (median **7.62s**); 42 were confirmed complete while the long turn remained active.

This recovery reused the same user text after earlier preparation. It is **not a controlled cold-preparation speedup**. The faster candidates were rejected: **100+ output tokens/sec per conversation together with stable 1M operation is not qualified**. The first rejected DSpark profile and the later memory-reuse candidate each caused one unexpected model restart in their separate trials; the recorded full recovery generation had none.

### Corrective memory-reuse trial: rechecked 19 October

A second candidate reused its newly allocated indexer score buffer for ReLU and weighting, rather than keeping several full-size intermediate tensors. A source-hash fence and an initialization gate protected the change. **80 GPU reference cases were bitwise equal** across the existing four GPUs; eight large-score checks reduced the isolated calculation's peak temporary memory from **3.00 GiB to 1.0625 GiB per GPU**. This measured one calculation, not total engine memory or full-context capacity.

Three actual DSH structured replies, each with 599 output tokens, passed at **164.24–165.74 streaming tokens/sec**. The 257,690-input-token DSH test returned its exact answer in **124.67 seconds**, while eight ordinary replies completed at a **4.07-second median**, with no allocator warning or restart during that stage.

The subsequent near-1M trial did **not** complete successfully. Its last saved controller snapshot contains **24 exact, persisted, retry-free short replies in 3.08–8.64 seconds**, including one eight-client burst. The controller stopped before writing a final disposition; its raw `running` status is preserved. Independent previous-container logs establish the failure: at **03:17:22 UTC on 18 October**, `dsv41_sparse.py` failed in `scores()` at `s.sum(dim=1)`, requesting **32 MiB with 21.75 MiB free**, and the model restarted once. No complete near-1M answer or second scheduled burst is verified. This trial is rejected, irrespective of the earlier successful math and 257K checks.

The exact saved original 1M deployment specification was restored. A fresh actual DSH reply and the original indexer source hash were verified after initialization. User storage mounts were unchanged: **167 existing histories and 188 files across 20 runtimes** retained their IDs and bytes. The experimental memory-reuse source and speculative profile were not promoted into the portable setup defaults.

The next optimization must preserve enough transient workspace at the full context length, with long preparation and diverse short traffic tested together. The isolated memory saving does not establish an end-to-end latency reduction. **Neither faster near-1M preparation nor stable 100+ tokens/sec per conversation with 1M has passed acceptance.**

## Preparation and answer generation are different costs

The preceding accepted near-1M run took 1,475.94 seconds overall. Its final-wire trace recorded **493 preparation calls of 2,048 tokens**, **1,466.18 seconds preparing context**, including **118.21 seconds yielding to ordinary requests**. Its 119-token answer streamed in 3.539 seconds, or **33.34 output tokens/sec**. Tokenization took about 2.24 seconds. Most of the wait therefore preceded answer generation.

Increasing preparation steps reduces repeated prefix serialization, HTTP calls and discarded one-token warm replies. It does not change the maximum conversation context or automatically accelerate the GPU's answer generation. GPU prefill chunks are a separate setting from these preparation steps.

## Actual DSH trials

| Profile / workload | Result | Disposition |
|---|---|---|
| Previous accepted near-1M profile | 1,007,697 input / 119 output; 24m36s overall; 33.34 streaming output tokens/sec | Retained as the rollback baseline |
| 8,192-token preparation steps with original model, first 256K trial | 257,699 input / 119 output; 137.27s overall; 14 correct overlapping short replies | Focused test; not near-1M acceptance |
| Narrow 131,072-token decode graph with eager long-context fallback | Three 599-token answers at 35.61–35.62 tokens/sec; 256K known answer skipped numbers and exceeded the requested range | Rejected; original attention and graph-runner files restored |
| DSpark block 5, static allocation 0.90 | Startup rejected: only 0.08 GiB remained in the static KV budget, below the 0.51 GiB sliding-window requirement | No inference acceptance |
| DSpark block 5, static allocation 0.925, 1,024-token prefill chunks | Three correct 599-token answers at **162.50–165.61 tokens/sec**; natural-language explanation at **69.56 tokens/sec** | Short-answer measurements only; rejected after the long-input failure below |

The first 256K preparation comparison used different traffic timing from the earlier 150.42-second sample. It is a recorded sample improvement, not a controlled percentage speedup. The two GPU code experiments are not deployed operating features.

### DSpark concurrency and the long-input failure

The DSpark candidate completed **31/31 correct, saved, retry-free replies** across bursts of 1, 2, 4, 8 and 16 client requests. The 16-client burst took **2.59–10.78 seconds per reply**, with **39.91–104.06 streaming output tokens/sec per conversation** and **170.76 combined output tokens/sec** over the full cohort window. These are different measurements: combined throughput is not the speed of one conversation. The server's cap was 16; the trace showed batches with four running requests and others queued, not sixteen continuously decoding requests.

The next 256K test failed around a **131,072-token cached prefix**. The low-ratio indexer in `dsv41_sparse.py` materialized a temporary weighted-ReLU score tensor. A **1,024 MiB allocation failed with 1,009.75 MiB free**, and the model restarted. The active long test and eight overlapping short tests did not complete correctly; those requests were cancelled in the disposable runtime. This failure is retained alongside the successful short measurements.

The candidate reported **1,181,184 full-cache slots** and **24,064 sliding-window slots**. That was enough nominal context capacity, but did not establish enough temporary working memory. Raising static allocation to fit draft weights and KV cache reduced the space available to transient computation. The fast candidate therefore does not establish deployable 100+ tokens/sec together with 1M operation.

The prose sample's configuration numbers were present, but its description of an extra request beyond a full FIFO position was imprecise. Such a request is rejected with a capacity response; it is not silently added to an unbounded queue. Its timing is a language-generation sample, not a general accuracy acceptance.

### Larger preparation steps and diverse short traffic

A separate near-1M test retained the original model and changed only the preparation step from 2,048 to 8,192 tokens. The final request counted 1,007,752 input tokens and asked for three random references distributed across the material plus a longer known answer. It did **not** return that answer. All **24 overlapping short replies** were correct, persisted and retry-free, taking **6.57–16.66 seconds**, including an eight-client burst. The model did not restart or report an allocator warning during this trial.

Preparation reached 679,936 tokens. The next 688,128-token warm request matched only **6,656 cached tokens** after the diverse short burst and began processing the missing prefix again. Its bounded warm call timed out after 30 seconds; DSH recorded one retry and the disposable test was cancelled. The exact cache-retention mechanism remains under investigation. The immediate failure was lost prefix reuse and reprocessing, rather than a model context rejection or an out-of-memory failure. A larger step alone is therefore not an accepted preparation optimization.

The operator restored the preparation step to **2,048** without restarting the GPU model. An initial same-payload recovery probe was intentionally cancelled after 180 seconds: it is **incomplete**, not a new full-1M pass and not a product failure. Its 16 overlapping short replies passed in **6.06–6.62 seconds**, with no retries. The complete recovery verification is summarized in the operating result above. Neither a Ready flag nor a completed short reply substitutes for that long-request outcome.

### Capture-width and source checks

The narrow-graph experiment preserved a 1,048,576-token product limit, but used a narrower short decode graph and attempted eager fallback for long contexts. It failed the known-answer gate and was removed. A failed answer alone does not prove its cause; it is sufficient reason not to retain that candidate.

A separate interpretation was corrected during the review: the old configuration exposed a default graph maximum of 512, but its actual startup log already captured batches `[1, 2, 4, 8, 12, 16]`. The observed memory change cannot be attributed to adding an explicit cap of 16.

The original files were read back before the DSpark trial:

| Installed file | SHA-256 |
|---|---|
| `layers/attention/deepseek_v4_backend.py` | `486900ed693af0573a941d6b6656ebc01ccb7ff1c44584e43ad3c0fb00a3c3a9` |
| `model_executor/runner/decode_cuda_graph_runner.py` | `f3e111f71fb07dfb3a293a6f3480969bf7b8876668c64a84572d648c73a0b727` |
| `layers/attention/dsv4/dsv41_sparse.py` | `b56eca87c3706edc9dd4db0f64431b87d52864495765bc3a85af6dbde21e2a5a` |

The rejected narrow override is absent from the restored deployment. The original tensor-parallel four-GPU model, 1M limit, scheduling overlays and storage boundaries remain the baseline.

## Preparation setting and measurement method

The operator-only environment variable `DSH_LONG_WARM_STEP_TOKENS` accepts multiples of 512 from 512 through 8,192; invalid values stop initialization. The source default remains 2,048. Clients cannot select this value through their request. Changing this step does not change GPU prefill size, long admission or the output budget. Numeric progress events record prepared/cached token counts, time inside preparation calls and time yielding to ordinary work; prompts and token IDs are not logged.

Tests use real DSH session creation, prompt processing, saved session events and the shared LiteLLM/model route in a disposable runtime with no production PVC or host-path mounts. Short prompts use fresh random tails so the whole user prompt is not a full-prefix cache hit. The final near-1M workload places three random references near the beginning, middle and end, and requests them with a longer known answer. Correctness is checked against the expected content, not merely HTTP success or a Ready flag.

Per-conversation streaming rate is `(reported output tokens - 1) / first-to-last-text seconds`. Full-request latency also includes preparation, waiting and harness delivery. Cohort throughput divides all outputs by the window from the earliest request start to the last completion. Different workloads and concurrent loads can have different rates; the 100+ structured-answer samples do not establish 100+ for every conversation.

The canonical forwarding/guard suite passed **39 Linux tests** and the portable setup suite passed **47 Linux tests**, without skips. The suites overlap. After the final documentation hash refresh, all **8 publication/hash/privacy checks** passed again. These checks validate the retained source and reproducible bundle; the DSH measurements above come from separate actual inference trials.

### Evidence provenance

One local controller accidentally reused its 256K summary filename during the later narrow-graph test. The original closed DSH histories were not changed. Twelve original cached probe records, the original model log, and the remaining two short plus one long session's complete event pages were separately preserved. The first long turn's persisted event duration is 137.022 seconds; the original controller's recorded completion/poll duration was 137.273 seconds. A reconstructed summary is not described as the original summary bytes. Subsequent profiles use distinct artifact names. Prompt hashes cover actual user events; runtime-context and agent-instruction events are kept separate.

## Authenticated route and history preservation

After the long run, the authenticated admin route returned three exact, saved, retry-free 119-token replies. The single request took **5.504s** (first text **1.740s**); the concurrent pair took **4.243s / 4.445s** (first text **0.563s / 1.015s**). Their streams delivered **33.34 / 33.93 / 36.26 tokens/sec**. These are post-recovery checks; the 42 replies in the operating result are the separate tests during long preparation.

All **164 original histories and 182 original session files across 20 runtimes** retained their IDs and byte hashes. The three new labelled admin test histories were archived through the normal application route; they were not confused with original records. Workspace and history mounts were not replaced by the model trials.

## Recovery and further optimization

After the out-of-memory failure, the exact previously accepted model specification was restored: **1,048,576 context, static memory 0.90, running cap 16, prefill chunks 512, aggregate prefill budget 1,024, prefix tails 8, two prefill requests and separate prefill/decode batches**. DSpark and the experimental attention override are removed. Workspace and history mounts were not changed by these model trials.

The memory-reuse trial reduced the isolated indexer calculation's temporary allocation, but the subsequent full-context OOM shows that total transient headroom is still insufficient for that speculative profile. Further work must measure the complete engine at long context, bound transient buffers and requalify concurrent short traffic. Increasing the cache budget alone does not close that gap. Optimization remains on the existing four GPUs.

[Previous allocator qualification](GPU_ALLOCATOR_QUALIFICATION_20261017.html) · [Small-question agent guidance](SHORT_REQUEST_LATENCY_20261018.html) · [SGLang V4.1 cookbook](https://github.com/sgl-project/sglang/blob/main/docs/cookbook/autoregressive/DeepSeek/DeepSeek-V4_1.mdx) · [Upstream decode-width proposal](https://github.com/sgl-project/sglang/issues/40441).

[Sanitized measurement summary](context-evidence/performance-optimization-20261018.json).
