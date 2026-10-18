# Small-request latency: diagnosis and bounded guidance

Observed 18 October 2026. This report concerns short-question latency, not a new 1M stress-test acceptance.

## What made a short prompt slow

An authenticated, read-only trace of the reported existing session found:

| Actual turn | Completion time | Model responses | Tool calls | Generated output tokens |
|---|---:|---:|---:|---:|
| Simple status question | 841.59 seconds | 75 | 74 | 22,649 |
| Workspace-location question | 62.57 seconds | 3 | 2 | 1,627 |

The status turn used 66 shell calls, seven writes and one presentation operation. Tool argument hashes were distinct; this was excessive scope and sequential work, not an identical-command retry loop. Its tools occupied about 15.72 seconds. First-text waits summed across its model responses were about 87.06 seconds. The remainder includes generation and other agent overhead; it cannot all be assigned to the GPU from this trace alone.

Individual requests in these turns stayed below 128K input tokens. They did not use the above-128K long-request preparation gate. Summed input usage across many calls is not a single request's context size. A small newly typed message can still lead to many model/tool steps in an established conversation.

The location turn generated 1,115 tokens in its final response alone. At approximately 33 tokens/second, a verbose answer itself consumes tens of seconds. The sidebar generation rate does not measure total question-to-completion latency.

## Safe change applied

The admin runtime received an appended, marked instruction block for simple status, location and factual questions. It asks the agent to identify the relevant target from conversation, batch independent read-only checks where practical, stop when the answer is established, and normally answer in a short paragraph or up to five bullets. It discourages unsolicited report/script/dashboard creation for these questions. Ambiguity calls for one focused question rather than broad exploration.

This is guidance, not a hard tool limit or output truncation. Explicitly detailed and broader implementation requests remain supported. Necessary verification and existing safety/user instructions retain priority. No model, GPU scheduling, context limit, compaction threshold, user history or workspace content was changed by this deployment.

The installed block was read back. All 87 session-store files backing 80 listed histories remained byte-identical during installation. The traced session remained listed afterward. No runtime restart was required. An existing synthetic session's persisted instruction event confirmed that the normal DSH loader refreshed the block.

Source startup generation now preserves existing AGENTS instructions and adds the marked block once, rather than replacing user instructions wholesale. That source change requires the next normal image build to enter a newly built image; this task applied the guidance directly to the persistent admin instruction file. Other users' runtimes were not rolled out.

## Retest results

Tests used disposable CPU DSH storage with the shared inference service. They did not add test messages to the real conversation.

| Test | First text | Total completion | Output tokens | Tools |
|---|---:|---:|---:|---:|
| Synthetic status before guidance | 2.137 s | 6.617 s | 127 | 1 |
| Same status, new session after guidance | 0.307 s | 4.066 s | 109 | 1 |
| Existing synthetic session after refresh | 0.367 s | 3.059 s | 79 | 1 |
| Workspace-location question after guidance | 0.519 s | 2.042 s | 36 | 0 |

All status answers reported the fixture's actual healthy state, zero pending items and correct workspace. The fixture was read, not modified. The location answer identified the actual synthetic session directory. The synthetic volume was ephemeral: its answer's generic assertion about persistent workspace behavior does not independently establish that canary's restart persistence. Production history preservation was checked separately as described above.

Fixed-output retests required exactly the integers 1–40, totaling 119 output tokens:

| Case | First text | Total completion | Streaming output rate |
|---|---:|---:|---:|
| First single request | 1.731 s | 5.575 s | 33.3 tokens/s |
| Warm single request | 0.255 s | 4.062 s | 33.3 tokens/s |
| Concurrent request A | 0.523 s | 4.091 s | 36.3 tokens/s |
| Concurrent request B | 0.313 s | 4.090 s | 35.3 tokens/s |

Streaming rates use `(output tokens − 1) / (last text − first text)`; total time includes request and polling overhead. The pair delivered approximately 58.2 output tokens/s aggregate including wall time. All four outputs matched exactly, persisted their prompts and completed with zero retries and zero tools.

The guidance reduced unnecessary output in this bounded sample. It did not improve intrinsic decode speed. These samples are not a controlled statistical benchmark or an SLA. They do not prove that every established conversation will now finish quickly, and the real 14-minute turn was not replayed because it would repeat production actions. Browser rendering latency, long-context fairness and the other coordinated GPU optimization trial are separate measurements.

## Preservation and rollback

The installer saves the original instruction bytes, refuses duplicate installation, checks for concurrent instruction changes, writes atomically, reads back the result, and compares every session-file hash before and after. Its preservation/duplicate/restore test passed. It never writes session files.

To roll back, first ensure the runtime is idle and compare the live instruction hash with the recorded installed hash. If no later edits exist, restore the verified pre-change instruction backup. If instructions changed afterward, remove only the exact managed block while preserving newer content. Do not restore or delete histories to reverse this guidance change.

Private evidence includes the sanitized event timing trace, per-step breakdown, installation hashes and synthetic test transcripts. Raw user conversation, credentials, endpoints and private paths are excluded from this public report. Synthetic histories were archived before removing the disposable pod.


## Post-GPU trial verification — 18 October 2026

The experimental GPU profiles were rejected and the previous model specification was restored exactly: **1,048,576 total context tokens, memory fraction 0.90, 512-token prefill chunks, aggregate prefill 1,024, at most two prefill requests, running-request cap 16 and no speculative decoding**. Gateway preparation is back to **2,048-token steps**. The current profile has no accepted decode-speed improvement from this cycle.

The trials explain why short benchmarks alone are insufficient:

| Trial | Observed result | Disposition |
|---|---|---|
| DSpark at memory fraction 0.90 | Startup rejected the cache allocation after draft weights loaded | Rejected |
| Narrower decode graph | Approximately 35.6 tokens/s on structured short answers; incorrect 256K answer | Rejected |
| DSpark at memory fraction 0.925 | 162–166 tokens/s on structured answers and about 69.6 on prose; CUDA OOM/restart during long/concurrent work | Rejected; fast figures are not current production performance |
| 8,192-token preparation steps | After a diverse eight-client burst, a prepared 679,936-token prefix matched only 6,656 tokens; reprocessing toward 688,128 exceeded the 30-second step timeout | Rejected; restored 2,048-token steps |

The last failure involved preparation/cache retention, with zero model restarts. Returning to smaller steps does not establish that the diverse-eight-client cache gap is fixed. The historical identical-prompt tests and fresh nonce-tail tests are different workloads.

### Complete near-1M functional recovery

A disposable actual DSH runtime submitted the same saved user text and pre-recorded reference answers. Cache reuse was not assumed, and this is not a controlled cold-speed comparison. The completed request used **1,007,752 input / 431 output tokens** and returned the exact three facts placed near the beginning, middle and end, followed by every integer from 1 through 200.

Completion took **1483.67 seconds (24m43.7s)**; generation streamed at **32.99 output tokens/s**. All **42** overlapping nonce-tail ordinary replies were exact and persisted, with **zero retries**, taking **6.07–10.60 seconds** (median **7.62 seconds**). The model stayed in the same generation with **zero unexpected restarts and zero mapping-OOM warnings**. All 43 saved answers were independently read back; the long user-text SHA-256 matched the pre-recorded input, and the answer oracle was derived again from the actual saved reference values.

The raw controller result remains `failed`: its additional preset required more than 500 output tokens. The complete, correct compact answer used 431 tokens. A separate reconciliation records **functional near-1M/retrieval/paired-concurrency acceptance passed**, while **the greater-than-500 output-token target was unmet**. No raw result was rewritten, and no greater-than-500 output-load acceptance is claimed.

This establishes one near-1M DSH request with ordinary requests in pairs. The configured cap of 16 is not a guarantee of 16 simultaneous decodes or two maximum-context requests. Reliable near-1M preparation during the diverse-eight-client burst remains an open performance gap.

### Actual authenticated gateway retest

Three new, labelled test histories were created through the normal admin login and gateway route to the existing runtime. Every saved response identified `deepseek-v4.1-flash` through `litellm-cluster`; all produced the exact 119-token answer with zero retries and zero tools.

| Request | First text | Total completion | Streaming output rate |
|---|---:|---:|---:|
| single | 1.740 s | 5.504 s | 33.34 tokens/s |
| pair-A | 0.563 s | 4.243 s | 33.93 tokens/s |
| pair-B | 1.015 s | 4.445 s | 36.26 tokens/s |

These timings include gateway/application requests and polling, but exclude browser painting and the operator's external network. The previous real-session diagnosis still matters: generating many sequential tool/model steps can dominate the total wait even when a small individual request is responsive.

### Final preservation and publication scope

Across **20 main runtimes**, all **164 original history IDs** and all **182 original session-file byte hashes** remained unchanged. Only the **three new admin-route test histories** were added (six new files); all three were archived through the normal API and retained. No test messages were appended to the original slow conversation. The disposable canary's synthetic histories were archived separately before removal.

The live model and gateway settings, rejected experiments and unresolved diverse-burst limitation are detailed in the [GPU trial and recovery report](PERFORMANCE_OPTIMIZATION_20261018.html). The concise-question guidance remains scoped to the admin runtime as described above. Other users' agent-guidance files were not rolled out by this work.
