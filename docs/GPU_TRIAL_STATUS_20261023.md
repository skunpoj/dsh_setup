# GPU and 1M qualification results — 23 October 2026

The latest candidate finished its test cycle and was **rejected**, then the saved baseline was restored. The 1,048,576-token configuration remains available. This candidate did not finish a near-1M answer or compaction, and does not establish a 100+ output-token/sec conversation.

## Completed actual DSH measurements

| Stage | Input tokens | Output tokens | Native whole turn | Stream-window output tokens/sec | Whole-turn output tokens/sec |
|---|---:|---:|---:|---:|---:|
| 128K | 124,074 | 576 | 57.139 s | 72.73 | 10.08 |
| 384K | 384,072 | 612 | 312.546 s | 79.19 | 1.96 |

Both stages completed with zero retries and passed the recorded full-window latency and GPU diagnostic gates. They used synthetic numeric context with distributed reference facts, not a realistic repository-quality benchmark.

Four ordinary DSH conversations overlapped. Each returned the exact 120-token numeric reply in **3.554–3.991 seconds**, with zero retries. Their individual whole-turn rates were **30.07–33.77 output tokens/sec**. Combined throughput was **117.75 output tokens/sec** across the **4.077-second client wall window**. Combined throughput is not 100+ tokens/sec for each conversation; this was one bounded four-client sample, not a sustained load test.

The final saved progress contains **108 exact short replies**, including **83 during near-1M preparation**. Maximum native turn time was **6.965 seconds**; maximum client elapsed time including polling/transport was **8.051 seconds**. All recorded short replies had zero retries. Earlier operator updates counted 105 before the final progress snapshot; 108 is the final saved count.

## Why the near-1M candidate was rejected

The candidate reduced the decode CUDA graph maximum batch from eight to four and tested an earlier switch to smaller preparation increments. At the near-1M stage, the model log recorded **four recoverable allocator-mapping warnings**. The strict memory gate stopped the test before promoting an unstable profile. The saved log recorded **zero uncaught CUDA out-of-memory errors, scheduler assertions, illegal-memory-access errors or tracebacks**. No completed near-1M response or compaction result exists for this candidate. Two simultaneous maximum-context conversations were not qualified.

The latest completed 128K/384K measurements must not be substituted for a full-context result. Historical near-1M successes belong to their dated profiles; they remain historical evidence, not acceptance of this optimization.

## Retained operating profile

| Setting | Restored value |
|---|---:|
| Total context ceiling | 1,048,576 tokens |
| Static GPU memory fraction | 0.922 |
| Maximum running requests | 8 |
| GPU prefill chunk / maximum prefill | 1,024 / 1,024 tokens |
| Allocated token pool | 1,091,840 slots |
| Decode graph maximum batch | 8 |

The running-request cap is a scheduler ceiling, not a guarantee that eight maximum-length contexts fit. Admission and bounded preparation remain necessary. Ordinary short work can overlap long preparation; long work still competes for the same four GPUs.

After restoration, an actual native DSH recovery reply returned READY in **3.736 seconds**. A second exact 80-output-token reply completed in **1.545 seconds**, with zero retries. These verify recovery through the canonical route, not a new near-1M performance pass. Further allocator/compaction and alternative-runtime trials remain pending a controlled GPU test window.

## Reading the rates correctly

Native whole-turn time includes preparation and generation. Stream-window output rate divides reported output tokens by the recorded streaming interval; it is an application timing estimate, not a GPU-only decoding benchmark. Client elapsed time also includes client transport/polling. A fast cached short reply does not measure cold million-token preparation. A configured million-token ceiling does not mean every request sends a million tokens.

## Preservation and operating procedure

The GPU operator retained all 472 pre-existing files in its isolated qualification-history set byte-for-byte and retained all 236 original histories; the set grew to 269 histories from test activity. This is the synthetic test store, not a count of production user histories. Owned test credentials and admission reservations were removed. Documentation publication does not restart workspaces, change accounts, rewrite histories or replace course media.

For the next trial, snapshot the current source/settings, use disposable test state, record exact input/output counts and short-request latency throughout preparation, enforce the warning gate, then verify the canonical native route after any restoration. Promote only after a substantial near-1M answer, compaction, tool continuation and ordinary-request responsiveness all pass on that exact profile.
