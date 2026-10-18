# DSH performance optimization on the existing four GPUs

## Operating result

The original **1,048,576-token model profile and 2,048-token preparation steps** are restored. The full recovery DSH turn returned the complete known answer for **1,007,752 input / 431 output tokens** in **24m43.7s**, with **zero retries, no allocator warnings and no model restart**. Its answer streamed at **32.99 output tokens/sec**. The preset output-length check required more than 500 tokens; the compact correct answer used 431, so that check remains failed and is preserved in the raw result. **42/42** paired short replies were exact, persisted and retry-free, taking **6.07–10.60s** (median **7.62s**); 42 were confirmed complete while the long turn remained active.

This recovery reused the same user text after earlier preparation. It is **not a controlled cold-preparation speedup**. The faster candidates were rejected: **100+ output tokens/sec per conversation together with stable 1M operation is not qualified**. Across the full experimental cycle, the rejected DSpark profile caused one unexpected model restart; the restored recovery generation had none.

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

The next engine optimization target is the transient indexer score calculation: avoid materializing several full-size score tensors, using a fused or tiled weighted-ReLU reduction with reference-equivalence and GPU-memory tests. That addresses the observed allocation failure; increasing the cache budget alone does not. This is further work on the existing GPUs, not a recommendation to add hardware.

[Previous allocator qualification](GPU_ALLOCATOR_QUALIFICATION_20261017.html) · [Small-question agent guidance](SHORT_REQUEST_LATENCY_20261018.html) · [SGLang V4.1 cookbook](https://github.com/sgl-project/sglang/blob/main/docs/cookbook/autoregressive/DeepSeek/DeepSeek-V4_1.mdx) · [Upstream decode-width proposal](https://github.com/sgl-project/sglang/issues/40441).

[Sanitized measurement summary](context-evidence/performance-optimization-20261018.json).
