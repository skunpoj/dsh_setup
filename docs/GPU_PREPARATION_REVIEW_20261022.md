# DSH preparation and concurrency review - 22 October 2026

The latest actual DSH run finished, but near-1M acceptance failed. Compaction was not started. The experimental GPU fusion is not accepted; the saved qualified 1M deployment specification was restored. Runtime recovery is checked separately. The context ceiling remains 1,048,576 total tokens.

## Results

| Actual DSH workload | Input / output tokens | Preparation | Whole turn | Output stream speed | Outcome |
| --- | --- | --- | --- | --- | --- |
| 128K stage | 124,076 / 647 | 43.35 s | 53.46 s | 71.75 tokens/s | Completed |
| 384K stage | 384,075 / 533 | 3m58.75s | 4m08.27s | 73.26 tokens/s | Completed |
| Near-1M stage | 1,002,081 / 1 | 24m35.29s | 24m40.77s | Not measurable | Failed: output allowance was one token; reply was `#` |
| Compaction, Stop/drain and retained-context recall | Not run in this qualification | Not run | Not run | Not run | Not reached after near-1M failure |

The completed 384K stage reduced preparation from 287.13 to 238.75 seconds, a 16.85% reduction in this ordered matched sample. Preparation-request time fell from 238.235 to 195.507 seconds; deliberate yielding to short requests fell from 44.488 to 38.853 seconds. This intermediate result does not establish a successful near-1M improvement.

## Short requests during near-1M preparation

Only requests that started and completed entirely inside the long turn are included below. These are complete native DSH turn latencies, not time to first token.

| Concurrent short workload | Replies | Median | p95 | Maximum |
| --- | --- | --- | --- | --- |
| Numeric | 41 | 4.79 s | 10.24 s | 13.21 s |
| Prose | 41 | 5.48 s | 9.13 s | 11.11 s |
| Fresh numeric conversations | 5 | 5.41 s | 10.50 s | 11.23 s |

All 87 replies met the recorded correctness/word-band checks and 15-second limit without retries. There were 106 short replies across all stages. One earlier candidate attempt stopped because a short prose answer exceeded its word-band check; that failure is retained separately rather than counted as a passed 384K run.

## Why the near-1M stage failed

The persisted DSH turn ended with `max-tokens`, one output token and zero retries. The final forwarding log independently recorded an output budget of one token. At the exact counted input of 1,002,081 tokens, a 1,048,576-token context with a 256-token reserve leaves 46,239 tokens before applying the configured output ceiling. Therefore the total context capacity alone does not explain the one-token allowance. A source readback found that the disposable runtimes managed-budget hook registers only for the canonical production origin. The private test proxy used a different origin, so that correction was not registered. A pure source-branch check confirmed one hook registration for the canonical origin and zero for the private test origin, without inference. This fixture mismatch leaves the SDKs character-based estimate in place. Correcting and retesting that fixture remains necessary; the observation is not evidence that the canonical production route lost its qualified budget handling.

Preparation used 298 prefix-warming requests. Of the 1,475.29 seconds, 1,287.805 seconds were recorded request time and 170.465 seconds were deliberate foreground yielding; the remainder includes other preparation overhead. Preparation is input processing/cache construction, not output generation. A one-token response cannot establish a meaningful output rate.

The candidate model process remained ready with zero unexpected restarts through the completed run. The failed answer is not evidence of another CUDA out-of-memory event. The experimental profile nevertheless failed its complete acceptance contract, so the saved qualified GPU configuration is restored rather than promoted. The kernel fusion is retained as an experiment, not installed as the portable setup default.

## Did we reach 100+ tokens/sec?

Not in this fresh substantial-output qualification. The two completed stages generated 647 and 533 tokens at 71.75 and 73.26 output tokens/sec respectively. Earlier short structured-output measurements above 100 tokens/sec do not establish that rate for near-1M prose. The near-1M output and compaction goals remain unaccepted.

These measurements used actual DSH, its LiteLLM forwarding path and the shared four-GPU backend. They are not Claude Code, Kilo or TrueForge near-1M acceptance. Output speed is output tokens divided by the recorded streaming interval; preparation and whole-turn latency are reported separately. The near-1M corpus used public repository code/documents with three known reference facts; it differs from the earlier numeric corpus, so its preparation time is not a controlled speed comparison with the older 28m32s run.

## Next acceptance gates

1. Trace and correct the one-token output allowance using the exact final forwarded payload and client profile; verify a substantial output reservation before spending another cold near-1M run.
2. Repeat the actual DSH near-1M task with checked source references, a substantial answer and ordinary requests continuing.
3. Only after that passes, test automatic compaction, Stop/drain, summary recall and persistence after replacement of a disposable runtime.
4. Promote an experimental GPU optimization only if all gates pass; preserve the qualified 1M configuration and original histories for rollback.

## Preservation and cleanup

All 36 original disposable test histories and their 72 session files remained hash-identical; all 61 resulting synthetic histories were retained. The test runtime profile was restored exactly, its worker and proxy were returned to their original stopped specifications, and the owned long-request reservation was released. No human workspace was restarted by this cleanup. These checks preserve recorded data; they are not the unrun compaction/replacement acceptance test.
