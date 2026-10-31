# DSH preparation and concurrency review - 22 October 2026

> **Historic measurement (SGLang, 22 Oct 2026).** Speed figures on this page keep that day's workload and timing boundary (streaming-window, forwarding-boundary or end-to-end rates), which differ from the current standard. Production moved to DeepInfer on 29 Oct 2026. Current figures, definitions and method: [LLM speed comparison (30 Oct 2026)](https://github.com/skunpoj/dsh_setup/blob/main/docs/deepseek-v41-h100/README.md#current-production-30-oct-2026-utc).

## Corrected-route qualification — 22 October 2026

The later actual DSH trial reserved 1,002,081 input tokens and 8,192 output tokens, but stopped at the strict memory-warning gate before a substantial answer. The last model cached-prefix counter was 765,952 tokens. The last acknowledged warming step was 720,896 tokens at 773.296 seconds; neither value is a completed full preparation. Four 20 MiB allocator mapping requests found only 15.75–17.75 MiB free. No uncaught CUDA out-of-memory exception or unexpected model restart was recorded during the trial.

| Check | Recorded outcome |
|---|---|
| Full near-1M answer | Not obtained; reserved input is not completed model processing |
| Ordinary replies alongside preparation | 53 passed their content checks, zero retries |
| Ordinary native turn latency | Median 4.66 s; maximum 11.78 s |
| Full preparation time / substantial-answer tokens per second | Not available because the long task did not complete |
| Near-limit compaction | Not started after the prerequisite failed |
| Short native reply after cancellation | 11,906 input / 7 output tokens; exact recovery reply, 0.996 s, zero retries |

The corrected V4 fusion is rejected rather than promoted. The short recovery reply occurred before the separate saved-profile rollback; it is not acceptance of a full near-1M task after rollback. The compatible unfused rollback profile has since passed actual loaded-source/image/argument checks: the 1,048,576 total-token ceiling, memory fraction 0.922, eight running requests and session-cache flag remain, while the rejected fusion is absent. A fresh native DSH request through canonical LiteLLM returned the exact recovery answer with 11,912 input / 12 output tokens in 3.825 seconds, zero retries and one matching canonical forwarding record. That short recovery does not qualify a fresh full near-1M workload. Retain the failed trial and earlier qualified profiles without presenting these results as a new near-1M or 100+ tokens/sec improvement.

## Persistence and cleanup

Only the disposable test worker was replaced. Its 130 histories / 260 compressed files remained byte-identical across replacement, including the original 61 histories / 122 files. Synthetic workspace data and a saved notebook survived. Final retained test state contained 131 histories / 262 files. The owned test workers were returned to their original stopped specifications, the admission holder was released and test credentials were revoked. Existing human workers were not restarted by this test.

## Output-budget qualification

The corrected private qualification route reserved 8,192 output tokens. A deliberately tiny near-1M reservation was refused before admission, warming or final dispatch. This is a private test-quality gate; ordinary production requests that legitimately request one output token remain allowed.

## Remaining performance qualification

Resolve the memory-warning gate on the existing hardware, then qualify a substantial actual DSH near-1M answer, tools and source checks, concurrent short-request responsiveness, and near-limit compaction with retained-context verification. Ordinary-service recovery is verified; the corrected full-context and compaction cases remain unqualified.

## Earlier output-budget trial

The following measurements and recovery settings belong to the earlier trial, not the current rollback profile.



This earlier DSH run finished, but near-1M acceptance failed. Compaction was not started. The experimental GPU fusion is not accepted; the compatible unfused rollback profile was restored. Rollback recovery was subsequently verified with an exact direct-model reply and an exact canonical LiteLLM reply; these short checks do not qualify near-1M output or compaction. The context ceiling remains 1,048,576 total tokens.

### Results

| Actual DSH workload | Input / output tokens | Preparation | Whole turn | Output stream speed | Outcome |
| --- | --- | --- | --- | --- | --- |
| 128K stage | 124,076 / 647 | 43.35 s | 53.46 s | 71.75 tokens/s | Completed |
| 384K stage | 384,075 / 533 | 3m58.75s | 4m08.27s | 73.26 tokens/s | Completed |
| Near-1M stage | 1,002,081 / 1 | 24m35.29s | 24m40.77s | Not measurable | Failed: output allowance was one token; reply was `#` |
| Compaction, Stop/drain and retained-context recall | Not run in this qualification | Not run | Not run | Not run | Not reached after near-1M failure |

The completed 384K stage reduced preparation from 287.13 to 238.75 seconds, a 16.85% reduction in this ordered matched sample. Preparation-request time fell from 238.235 to 195.507 seconds; deliberate yielding to short requests fell from 44.488 to 38.853 seconds. This intermediate result does not establish a successful near-1M improvement.

### Short requests during near-1M preparation

Only requests that started and completed entirely inside the long turn are included below. These are complete native DSH turn latencies, not time to first token.

| Concurrent short workload | Replies | Median | p95 | Maximum |
| --- | --- | --- | --- | --- |
| Numeric | 41 | 4.79 s | 10.24 s | 13.21 s |
| Prose | 41 | 5.48 s | 9.13 s | 11.11 s |
| Fresh numeric conversations | 5 | 5.41 s | 10.50 s | 11.23 s |

All 87 replies met the recorded correctness/word-band checks and 15-second limit without retries. There were 106 short replies across all stages. One earlier candidate attempt stopped because a short prose answer exceeded its word-band check; that failure is retained separately rather than counted as a passed 384K run.

### Why the near-1M stage failed

The persisted DSH turn ended with `max-tokens`, one output token and zero retries. The final forwarding log independently recorded an output budget of one token. At the exact counted input of 1,002,081 tokens, a 1,048,576-token context with a 256-token reserve leaves 46,239 tokens before applying the configured output ceiling. Therefore the total context capacity alone does not explain the one-token allowance. A source readback found that the disposable runtimes managed-budget hook registers only for the canonical production origin. The private test proxy used a different origin, so that correction was not registered. A pure source-branch check confirmed one hook registration for the canonical origin and zero for the private test origin, without inference. That earlier fixture mismatch left the SDKs character-based estimate in place. That fixture was subsequently corrected and retested, as recorded above; the observation is not evidence that the canonical production route lost its qualified budget handling.

Preparation used 298 prefix-warming requests. Of the 1,475.29 seconds, 1,287.805 seconds were recorded request time and 170.465 seconds were deliberate foreground yielding; the remainder includes other preparation overhead. Preparation is input processing/cache construction, not output generation. A one-token response cannot establish a meaningful output rate.

The candidate model process remained ready with zero unexpected restarts through the completed run. The failed answer is not evidence of another CUDA out-of-memory event. The experimental profile nevertheless failed its complete acceptance contract, so the saved qualified GPU configuration is restored rather than promoted. The kernel fusion is retained as an experiment, not installed as the portable setup default.

### Did we reach 100+ tokens/sec?

Not in this fresh substantial-output qualification. The two completed stages generated 647 and 533 tokens at 71.75 and 73.26 output tokens/sec respectively. Earlier short structured-output measurements above 100 tokens/sec do not establish that rate for near-1M prose. The near-1M output and compaction goals remain unaccepted.

These measurements used actual DSH, its LiteLLM forwarding path and the shared four-GPU backend. They are not Claude Code, Kilo or TrueForge near-1M acceptance. Output speed is output tokens divided by the recorded streaming interval; preparation and whole-turn latency are reported separately. The near-1M corpus used public repository code/documents with three known reference facts; it differs from the earlier numeric corpus, so its preparation time is not a controlled speed comparison with the older 28m32s run.

### Acceptance gates identified at that earlier stage

1. Trace and correct the one-token output allowance using the exact final forwarded payload and client profile; verify a substantial output reservation before spending another cold near-1M run.
2. Repeat the actual DSH near-1M task with checked source references, a substantial answer and ordinary requests continuing.
3. Only after that passes, test automatic compaction, Stop/drain, summary recall and persistence after replacement of a disposable runtime.
4. Promote an experimental GPU optimization only if all gates pass; preserve the qualified 1M configuration and original histories for rollback.

### Preservation and cleanup

All 36 original disposable test histories and their 72 session files remained hash-identical; all 61 resulting synthetic histories were retained. The test runtime profile was restored exactly, its worker and proxy were returned to their original stopped specifications, and the owned long-request reservation was released. No human workspace was restarted by this cleanup. These checks preserve recorded data; they are not the unrun compaction/replacement acceptance test.

The earlier rollback snapshot recorded 1,048,576 total tokens, DSpark block size 5, 1,024-token GPU prefill chunks, static memory fraction 0.923 and at most eight running requests. At that earlier checkpoint, the saved model specification and source hash matched, with zero unexpected restarts. Direct-model and canonical-route health replies completed in 0.19 and 0.23 seconds respectively; these tiny replies are recovery checks, not throughput benchmarks.
