## Latest implementation and qualification

**19 October 2026: the DSpark profile is qualified for the recorded workloads.** The current portable defaults match the promoted profile. The complete near-1M, cached-output and tool tests ran before a handover with identical GPU arguments and the same four runtime-module hashes. Startup, structured replies, corrected concurrency delivery and prose checks ran again after that handover. These are distinct test scopes, rather than a claim that every long workload was rerun after it.

| Setting | Current qualified profile |
|---|---|
| Total context ceiling | 1,048,576 tokens |
| Speculative decoding | DSpark block 5 |
| Static GPU memory fraction | 0.923 |
| Active request / decode graph cap | 8 / 8 |
| GPU prefill chunk / maximum prefill | 1,024 / 1,024 |
| Prefix tails | 16 |
| Long admission | One active request above 128K, one bounded FIFO waiter; ordinary requests bypass long admission |

### Measured results and their scope

| Workload | Result | Interpretation |
|---|---|---|
| Full near-1M DSH request | 1,007,752 input / 431 output tokens; exact saved answer; 1,342.17 seconds overall; 147.82 streaming output tokens/sec | Long preparation and output generation are different costs. No retry, allocator warning or unexpected restart in this run. |
| Ordinary replies during near-1M work | 46 correct, saved, retry-free replies; paired median 5.08 seconds; two eight-client bursts | One long request can coexist with ordinary work. This is not two full-1M requests or a latency SLA. |
| Cached near-1M follow-up | 1,008,209 input / 1,199 output tokens; exact answer in 14.86 seconds; 158.32 streaming tokens/sec | Reused context, not a new cold-preparation benchmark. |
| Real tool continuation | 1,009,673 input tokens; create/read/delete marker sequence passed in 13.42 seconds; cleanup verified | Actual file/tool behavior in a disposable runtime, not a Production data mutation. |
| Fresh post-handover concurrency | 31/31 exact, saved, retry-free replies across 1, 2, 4, 8 and 16 clients | The active cap is eight; a 16-client burst can queue. All 16 are not guaranteed to decode simultaneously. |
| Natural-language explanation | Initial answer required factual correction; reviewed correction streamed at 96.76 tokens/sec | Structured 164–166 tokens/sec samples do not establish 100+ for all prose or general analytical accuracy. |
| History preservation | 167 original histories / 188 original session files across 20 main runtimes retained their IDs and bytes | The inference change did not require replacing user workspace mounts. |

### Reliability boundaries and lessons

Memory remains tight: a one-second NVML sample observed a minimum of 38 MiB free per GPU during the capacity workload. This is sampled telemetry, not a continuous peak bound or proof of universal stability. Keep admission control and the exact last qualified rollback configuration.

Earlier trials failed from temporary score/dequantization allocations despite apparently sufficient KV-cache slots. Smaller score tiles, reduced intermediates and additional dynamic headroom enabled the current workload. Startup equivalence checks complement full actual DSH tests; neither replaces the other.

A Windows control-channel failure initially marked one follow-up controller failed. Its raw result remains preserved. All 16 saved native replies were independently recovered and verified, and the corrected single-channel fresh test then passed all 31 replies. That transport incident is not relabelled as a model OOM or silently removed.

The managed DeepSeek aliases declare 1M in all 20 main web profiles; other model entries retain their own budgets. These results concern native DSH through shared inference. They do not by themselves repeat every Claude Code/TrueForge capacity test or all application security checks.

See the [sanitized qualification record](https://github.com/skunpoj/dsh_setup/blob/main/docs/context-evidence/dspark-qualification-20261019.json) and the [detailed optimization report](https://github.com/skunpoj/dsh_setup/blob/main/docs/PERFORMANCE_OPTIMIZATION_20261018.html) for the workload-specific source records.


### Full latest-test coverage

| Check | Recorded result |
|---|---|
| 256K capacity | 257,691 input tokens; correct saved answer in 130.57 seconds; eight overlapping short replies, median 3.56 seconds. The seven-token answer is too short for a useful decode-speed benchmark. |
| Fresh structured output | Three exact, persisted 599-token answers at 164.60–166.11 streaming output tokens/sec. |
| Startup reference gates | 80 score cases, eight tiled cases, 132 FP4 cases and eight memory checks passed; optimized Python is refused before the gates can be bypassed. |
| Full-capacity ordinary bursts | Eight-client cohorts passed at prepared prefixes of 655,360 and 917,504 tokens, with the long request still active. |

| Fresh clients after handover | Individual whole-request time | Combined cohort output tokens/sec |
|---|---|---:|
| 1 | 1.29 seconds | 92.35 |
| 2 | 2.59–2.84 seconds | 83.76 |
| 4 | 2.87–3.88 seconds | 122.43 |
| 8 | 3.20–5.98 seconds | 158.45 |
| 16 | 3.11–11.21 seconds | 169.01 |

The five fresh groups total 31 unique saved replies. All were exact and retry-free. Combined throughput includes the entire request window and is distinct from one conversation's streaming speed. The model can admit eight active requests; excess clients may queue.

### Checkpoint scope

The results above remain bound to the checkpoint and four runtime-source hashes qualified on 19 October 2026. A separate task is staging DeepSeek-V4.1-Flash-1017, pinned revision `1bae0e1088993b9b82de08f59de5be5a34e42170`. That staging work does not change which model these results tested, and does not qualify the new weights. Re-run the relevant acceptance checks before attributing the recorded performance to that checkpoint.
