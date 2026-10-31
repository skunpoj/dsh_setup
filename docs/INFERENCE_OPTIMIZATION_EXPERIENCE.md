# DSH inference optimization — decisions, trials and lessons

> **Historic measurement (SGLang trials, 15–23 Oct 2026).** Speed figures on this page keep that day's workload and timing boundary (streaming-window, forwarding-boundary or end-to-end rates), which differ from the current standard. Production moved to DeepInfer on 29 Oct 2026. Current figures, definitions and method: LLM speed comparison (30 Oct 2026).

## Latest near-1M and compaction status - 22 October 2026

The latest actual DSH near-1M run **failed acceptance**: **1,002,081 input / 1 output token**, **24m35.29s preparation**, **24m40.77s whole turn**, zero retries. The final forwarding allowance was one token; this is not a successful substantial-output result. **Compaction was not started.** The experimental GPU profile is not promoted; rollback preserves the qualified 1M configuration.

Completed 128K/384K stages reached **71.75 / 73.26 output tokens/sec**. During near-1M preparation, 41 numeric replies had **4.79s median / 10.24s p95**, 41 prose replies **5.48s median / 9.13s p95**, and five fresh numeric conversations **5.41s median**; all 87 completed within 15 seconds. **100+ tokens/sec was not established in this fresh substantial-output test.** See [complete results, failure explanation and remaining gates](GPU_PREPARATION_REVIEW_20261022.html).


This record explains how the existing four-GPU deployment reached DSpark-enabled 1M operation, what failed, why preparation remains expensive and which claims the tests support. It consolidates the dated performance trials, 1017 checkpoint qualification and setup guide. Recorded measurements below are from those tests; opening this document does not start a benchmark.

## From candidate support to qualified operation

The earlier statement that draft-weight availability and memory fit still required confirmation described the investigation stage. DSpark was subsequently loaded and exercised through real DSH requests, including a near-1M turn and its tool continuation. It is no longer merely an untested runtime capability. The pinned checkpoint was checked against its file manifest: 83 file sizes, 48 weight shards and 49 LFS hashes; 96,085 tensor names matched the earlier checkpoint. Runtime configuration alone was not used as proof of successful speculative execution.

DSpark uses the model's draft path to propose candidate output tokens, which the target model verifies together. Accepted proposals can reduce sequential decoding work. Its extra weights, state and working buffers compete with the KV cache and temporary attention computation for GPU memory. Runtime support, successful startup, a fast short answer and stable full-context execution are four separate gates.

The accepted 19 October configuration uses DeepSeek-V4.1-Flash-1017, DSpark block five, 1,048,576 total tokens, static memory fraction 0.923, eight active requests/eight decode graph slots, 1,024-token prefill chunks and batch budget, and 128 MiB attention-score tiles. Long admission allows one expensive request and one bounded FIFO waiter; ordinary requests remain concurrent. The model's active cap does not mean eight full-1M requests fit.

## Why earlier fast candidates failed

| Observation | What it established | Decision or correction |
|---|---|---|
| Large nominal KV pool | Enough recorded token slots did not establish transient-memory headroom | Qualify actual long input, decoding and simultaneous short work |
| DSpark at static fraction 0.90 could not initialize its sliding-window cache | The remaining static budget was insufficient for that candidate | Adjust allocation and separately recover temporary working memory |
| Fast short outputs followed by a 256K OOM | A 1,024 MiB temporary score allocation failed with 1,009.75 MiB free | Reject the candidate despite short-request speed |
| Later near-1M trial requested 32 MiB with 21.75 MiB free | A small final allocation failure still interrupted the model; it did not prove only that amount of extra memory would make all future workloads safe | Reject, retain evidence and restore the qualified profile before another trial |
| Reused score buffers, tiled score computation and bounded FP4 dequantization passed isolated GPU math checks | The patched operations matched the tested reference calculations and reduced their isolated peaks | Continue to full-context acceptance; do not add separate peak savings into a claimed global saving |
| Static allocation reduced from 0.925 to 0.923; request/graph caps reduced | More space was left for transient work while ordinary parallel service remained possible | Retest cold input, cached continuation and mixed traffic |
| New checkpoint with 256 MiB tiles returned a correct long answer but logged recovering allocation warnings | Correct content alone did not pass the zero-warning stability criterion | Reject that profile and qualify 128 MiB tiles |
| Windows CRLF versus Linux LF changed an expected source hash | The source-verification setup failed before accepted inference | Normalize generated source and verify the actual Linux CLI; do not classify this as GPU OOM |
| Operator connection loss triggered an early rollback | A disconnected controller was not evidence of failed model execution | Read actual model/session state before deciding whether rollback is justified |

Startup math gates cover 80 score cases, eight tiled cases, 132 FP4 cases and eight FP4 memory checks. Source-hash fences stop initialization when upstream patch targets change. They complement actual DSH acceptance; they do not replace it.

## Where the long wait comes from

There are two independent controls: the gateway's **preparation step** and the GPU's **prefill chunk**. The gateway prepares an increasing prefix of the final forwarded payload so short work can progress between preparation calls. The GPU processes admitted input in bounded prefill chunks. Neither number is the maximum context length.

One recorded earlier near-1M trace contained **493 preparation calls of 2,048 tokens**. It spent **1,466.18 seconds preparing context**, including **118.21 seconds yielding to ordinary work**; tokenization took approximately **2.24 seconds**. The final 119-token answer streamed in **3.539 seconds**. This trace measures time inside preparation calls, which includes GPU work; it does not isolate all HTTP/serialization overhead as a separately measured component.

Larger preparation steps can reduce repeated prefix serialization, HTTP requests and discarded warm-up outputs. They can also increase uninterrupted work and affect cache reuse under diverse traffic. An 8,192-token preparation experiment lost prefix reuse in the recorded mixed workload; the qualified default remains **2,048**. GPU prefill chunks remain **1,024**. A faster cached turn is cache reuse, not evidence that cold GPU prefill became equally fast.

Earlier integration work also found tokenizer/chat-template defaults diverged for tool definitions and warming did not match the final forwarded payload. Counting and preparation were moved to the final forwarding boundary and the relevant defaults aligned. Otherwise the final request could process the full prompt again. Separately, a client character-count estimate could collapse the output allowance to one token despite room according to the exact tokenizer; the managed route received a bounded output-budget correction. These were payload/budget issues, distinct from GPU speed.

## Accepted measurements and their limits

| Actual DSH case, 1017 checkpoint | Recorded result |
|---|---|
| Cold near-1M | 1,007,752 input / 431 output; 27m33.97s overall; first text 1,650.96s; 149.15 streaming output tokens/sec |
| Short work alongside cold preparation | 60/60 correct persisted replies; 3.13–9.22s; paired median 5.11s; two eight-client bursts |
| Cached substantial answer | 1,008,209 input / 1,199 output; 15.13s overall; 159.22 streaming output tokens/sec |
| Real file tool continuation | 1,009,686 input; 12.94s; file create/read/delete and saved tool result verified |
| Three structured 599-token outputs | 163.34–166.48 streaming output tokens/sec per conversation |
| Short-client bursts | 31/31 correct persisted replies across 1, 2, 4, 8 and 16 clients; additional clients queue above eight active slots |
| Stability during accepted cold generation | Zero automatic retries, allocator mapping warnings or unexpected model restarts |

The complete memory trace reached a minimum of **36 MiB free per GPU** including follow-ups, versus **38 MiB during the cold stage**. These are different observation windows, not conflicting measurements. Headroom remains tight.

Streaming output rate excludes the cold preparation wait. Whole-turn latency includes preparation, queuing, tools and delivery. Aggregate cohort throughput divides total outputs by the complete cohort window. Report these separately; a high aggregate rate is not the speed of every conversation. Earlier prose samples were below 100 tokens/sec, and structured outputs do not establish a universal prose rate.

After short-client bursts, an optional later near-1M prose turn re-entered cold preparation and was cancelled. Its cache-miss cause was not isolated. Durable history preservation and immediate hot continuation do not guarantee a later turn retains the same GPU KV cache.

## Remaining optimization and acceptance work

The full controlled matrix of 512–1,024-token answers at concurrency 1, 2 and 8, using short, 128K and near-1M inputs, is not complete. Keep source-backed answer checks, first-text latency, streaming rate, aggregate throughput and memory/restart results for every cell. Fresh near-1M qualification for Claude Code and TrueForge is separate from native DSH acceptance.

Any next optimization should preserve the total context limit, exact final-payload preparation, bounded long admission and short-request responsiveness. Change one variable at a time, retain rejected results and distinguish overhead reduction from kernel or decode improvements. Restore the qualified configuration after actual regression; retain user data and newer histories. No production setting is changed by this documentation update.
