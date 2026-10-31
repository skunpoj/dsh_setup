# GPU performance and near-1M results

> **Historic measurement (SGLang, 23 Oct 2026).** Speed figures on this page keep that day's workload and timing boundary (streaming-window, forwarding-boundary or end-to-end rates), which differ from the current standard. Production moved to DeepInfer on 29 Oct 2026. Current figures, definitions and method: [LLM speed comparison (30 Oct 2026)](https://github.com/skunpoj/dsh_setup/blob/main/docs/deepseek-v41-h100/README.md#current-production-30-oct-2026-utc).

## GPU performance and 1M operation — 24 October 2026

### Identifier-attribution checkpoint protection — 24 October 2026

The compaction guard is active on all 34 running workers across DSH, DSH2 and DSH3. It was loaded through DSH's supported profile hot reload, without restarting DSH, Jupyter or notebook kernels. Existing compaction instructions, checkpoint framing, model settings and storage mounts remain unchanged.

Before a future summary is adopted, the guard checks claims that the assistant included opaque identifiers against the actual user and assistant messages. For example, identifiers supplied only by the user cannot be credited to an assistant-produced guide. Unsupported or uncertain attribution holds compaction before checkpoint adoption, releases no successful candidate text and does not retry through recovery. Ordinary chat bypasses this check.

Verification passed 51 source/component checks for each repository-specific installer, six native compaction cases, and official file-watcher activation/removal checks. All 34 live workers passed four in-process synthetic checks each: ordinary-chat bypass, supported attribution, explicit unsupported attribution and unsupported “assistant guide” wording — 136 checks in total. These checks made no real model calls and did not repeat near-1M testing.

A memory-only native compaction produced a checkpoint that correctly attributed the identifiers to the user, retained the generic assistant guide and did not invent acceptance evidence: 4.673 seconds, 1,178 input / 407 output tokens. The initial four real-model requests included a leading-answer smoke check, a truncated neutral reply and an ambiguous origin field; their original results remain preserved. One later question explicitly asked which conversation speaker supplied the identifiers, using the same saved checkpoint and unchanged native framing. It returned the correct user role and a ten-word evidence quote that exactly matched the checkpoint: HTTP 200, 0.519 seconds, 557 input / 43 output tokens, complete stop. The question supplied no expected role or answer. This closes the specific speaker-origin ambiguity for that check; it does not establish general summary faithfulness. Five real-model requests are recorded in total, with zero client retries. No compaction or near-1M test was repeated, and no user session was persisted or changed.

Pod identities, container restart counts, existing plugin records and protected DSH/Jupyter process identities stayed unchanged. Existing history/attachment/workspace metadata fingerprints matched before and after each activation; these are metadata checks, not a new byte-by-byte audit of all user files. Only versioned guard files and one added profile entry were written.

The guard applies to compactions started after its activation; earlier summaries and already-started requests are unchanged. Its persistent profile entry and code remain available on the existing workers' state volumes. Brand-new workers using an older image still require the same activation or an image containing the committed build-time guard. The live add-on checks the tested English identifier-attribution patterns; it does not certify every summary statement. On a hold, review the affected conversation rather than treating the rejected summary as an accepted result. The original history is not replaced; rejected-candidate details remain on the in-memory error object.

### Small recall and summary-quality follow-up — 24 October 2026

Eight bounded model requests across the initial six checks and two focused follow-ups tested synthetic conversations, with zero client retries. The targeted checks passed: silence was not treated as acceptance, identifier roles remained distinct, rejected and pending states were retained, genuine ambiguity was preserved, and quoted instructions were not followed. The focused revision-2 follow-up corrected the claim that visible assistant content was missing.

**Remaining limitation:** One attribution limitation remains: the final summary credits the assistant guide with identifiers that were present only in the user input. These targeted passes are not a full summary-faithfulness acceptance, and do not erase the original trial-W quality failures.

The build-time candidate passed 26 component checks, including independent verification of unchanged model routing, token policy, cancellation, tool definitions and summary framing. It refuses unreviewed upstream source. At that stage, the prompt-only patch remained a local candidate and had not been merged or activated. No near-1M test was repeated. These small tests did not read or write user histories, modify user files, restart workspaces or change the shared model configuration.

### Saved S history: automatic compaction and recovery — trial W

The remaining saved-S-history case completed automatic compaction on the shared baseline, using a tiny follow-up on a fork of the existing history. No new million-token capacity prompt or model reload was used. The original R and S histories remained unchanged.

| W check | Verified result |
| --- | --- |
| Summary request | 1,003,068 input / 885 output tokens |
| Preparation at the forwarding boundary | 27m26.44s |
| Automatic summary phase | 27m44.07s, from native compaction/start to compaction/end |
| Summary output stream | 71.80 output tokens/sec over 12.326s, from first upstream text delta to completed body |
| Following reply | COMPACT_OK; 196,968 input tokens; 83.55s after summary completion |
| Whole initial client turn | 29m08.95s, including compaction and the following reply |
| Short requests | 28 total, including two startup checks; 26 completed entirely during the summary |
| 26 overlapping short replies | 6.09s median / 10.23s nearest-rank p95 / 12.26s maximum; zero retries; all below 15s |
| Explicit reference and three-fact recall | Passed on the same compacted session in 1.85s / 2.30s |
| Actual tool continuation | File write 4.30s; changed, previously undisclosed nonce read 3.85s; zero retries; synthetic file removed |
| Cancellation recovery | An active user-aborted turn and backend drain were verified; the same session replied RESUMED in 0.61s |
| Replacement persistence and restoration | 398 histories / 796 history files in the test runtime stayed byte-identical across an actual disposable pod replacement; original profile and stopped test specs restored; test key revoked and temporary resources removed |

The first broad reference query returned the other identifier retained in the summary, so its exact-match check failed. An explicit prefix query then recalled the intended identifier. All three original facts were retained verbatim and the subsequent three-bullet answer was accurate. However, the summary incorrectly stated that the earlier guide had been accepted without revision requests; no human acceptance was recorded. Strict summary-quality acceptance therefore remains failed. Some short prose replies also used imprecise wording about saving variables, separate from their passing timing and format checks.

The two short-request lanes ran repeatedly alongside the summary. Client latency includes RPC and observation time; p95 uses nearest rank. The 71.80 tokens/sec figure belongs to this 885-token compaction summary and is not a matched comparison with the earlier capacity workload. File-byte persistence was verified across replacement; a new native chat turn after that replacement was not tested. The baseline was unchanged at the 24 October, 07:35 ICT closeout readback.

### Preflight correction and recovery — trial U

**Startup checks passed; automatic compaction did not launch.** A local preflight requested an obsolete tail-tokenizer field absent from the summary-budget configuration. Recovery restored the original model, profile and private test workloads and revoked the temporary key. This was a harness setup failure, not a new near-1M capacity result.

| U check | Recorded result |
| --- | --- |
| First numeric / prose startup replies | 7.71s / 10.26s client elapsed |
| Following numeric / prose startup replies | 1.79s / 3.84s client elapsed |
| Diagnostic GPU counter points | Zero new allocator retries/OOMs on four GPUs; no raw periodic compaction-window proof |
| Tokenizer-only summary budget | 1,003,068 input + 8,192 reserved output + 256 reserve = 1,011,516 tokens; no inference |
| Automatic compaction | Not dispatched; no new compaction speed or concurrent-compaction latency result |
| Preservation | 32 human workers / 256 selected history-and-attachment files unchanged; 386 original fixture sessions / 772 original files retained |
| Fixture inventory after recovery | 390 sessions / 780 files, including four new startup-test sessions |

Both prose explanations correctly distinguished saved files and volatile Python state. The following reply used 176 words, exceeding the requested 120–160 range while meeting the declared 85–210-word diagnostic gate. This is not strict format compliance. The local suite missed the stale configuration dependency; the correction adds a complete preflight with the actual saved configuration and current fixture identity checks before changing the model. The verified count and saved conversation are reused without another capacity prompt. U does not establish compaction acceptance; see the latest follow-up above.

### Compaction-only follow-up and recovery — 24 October

**Trial S was rejected before automatic compaction began; recovery is verified.** It did not repeat the 1M capacity test. There is no new compaction speed or near-1M throughput measurement.

| S check | Actual result |
| --- | --- |
| First startup numeric / prose replies | 6.42s / 9.44s client elapsed |
| Following startup numeric / prose replies | 1.82s / 3.85s client elapsed |
| Two short replies during the failed attempt | 4.05s / 4.07s; zero retries; configured checks passed |
| Automatic compaction | Did not start; total-token guard rejected the oversized request before long model inference |
| Four-rank GPU observations | Complete coverage of the two short replies; zero allocation retries and OOMs in that window |
| Recovery | Original model and fixture profiles restored; temporary test key revoked and its Secret absent |
| User-state integrity scope | 32 workers / 256 selected session-and-attachment files matched the fresh canonical inventory |
| Separate qualification fixture | 379 original sessions / 758 original files preserved |

The short replies were **not concurrent with compaction**. One prose reply incorrectly implied that opening a saved notebook automatically reruns its cells; the recorded keyword check is narrower than full factual correctness.

The native compaction check runs before pending user messages enter its surface. The first recent tail therefore became durable only after that check, and the next request exceeded the budget. The corrected follow-up forks the saved primed history and sends a small continuation, without another large tail or capacity test. Actual compaction, Stop/resume, persistence and short responsiveness remain a separate runtime result.

The recovered baseline retains **1,048,576 context tokens, DSpark, memory fraction 0.922, running cap 8 and 1,024 / 1,024-token prefill**. Its shared GPU reservation was released. The S overlay was not permanently adopted. R’s narrative-quality failure and final counter gap are not retrospectively repaired.

[Allocator-telemetry helpers](https://github.com/skunpoj/dsh_setup/tree/main/gpu-stack/qualification/allocator-telemetry) include 32 passing CPU checks; they do not install a runtime or run inference.


**Recorded near-1M capacity benchmark — trial R:** **1,002,051 input / 636 output tokens**, **29m26.56s preparation**, **29m32.09s to first text**, **29m44.28s client elapsed**, and **61.56 streaming output tokens/sec**. The streaming rate excludes initial preparation. Preparation is measured at the forwarding boundary; time to first text also includes tokenization and forwarding overhead. **100+ tokens/sec per near-1M conversation has not been reached.**

The startup hook exercises the original kernel implementation before the KV cache is allocated and before readiness. All four GPUs completed the bounded initialization in **9.61–10.09s each**. The model weights and kernel mathematics were not changed. First numeric/prose startup requests completed in **8.73s / 10.32s client elapsed**; the following pair completed in **1.30s / 2.83s**. All four passed their content checks without retries and remained below the unchanged **15s client limit**. The first pair was slightly slower than the matched earlier baseline; this is not a general speedup claim.

The subsequent near-1M turn completed with **zero request retries**. During the test, **110/110 short replies** passed their recorded content checks: **6.03s median, 10.06s p95 and 14.06s maximum client latency**. **104 replies began and finished within the long turn**, with **6.03s median, 10.06s p95 and 14.06s maximum**. These are full client timings, not short-output streaming rates.

The result establishes completed near-1M capacity with concurrent short replies, rather than full acceptance of the optimization. The long answer repeated the supplied core facts but introduced unsupported platform claims, so strict source-only narrative acceptance failed. The last captured GPU counters stop about five seconds before client completion; zero captured allocation/OOM deltas do not establish complete-turn coverage. A large progress-read transport failed after the answer had completed; its compressed, hash-verified archive preserved the native turn and all 110 short results. This observer failure is separate from a model failure. R did not run compaction.

The original model specification was restored and matched its saved SHA-256; an actual native request returned **READY**. The **32-worker / 256 session-and-attachment-file snapshots were byte-identical** before and after the trial. No running kernels were observed; these snapshots did not hash every arbitrary workspace file. All four recovery steps and removal of the owned fixture credential were verified. The startup hook and tile candidate were experimental in R, not permanently adopted. R did not run compaction.

### Earlier cold measurement — 21 October

The earlier actual DSH case used **1,008,049 input / 540 output tokens**, **28m32.25s forwarding-boundary preparation**, and **66.00 wire-streaming tokens/sec**. Its native time to first text was **28m38.13s**. R forwarding preparation is about **54s longer**; its native streaming rate is lower. The workload and timing boundaries differ, so the comparison does not demonstrate a controlled performance gain or identify a single cause.

### Earlier full-model trial N — stopped at the responsiveness limit

The sole final N request tokenized **1,002,056 input tokens**, but completed only partial prefill. Its numeric short reply took **13.70s native / 14.11s client elapsed**; its prose short reply took **15.83s native / 16.06s client elapsed**. Both passed their recorded content checks with zero retries. The prose client time exceeded the unchanged **15-second** safety ceiling, so the owned long request was stopped. **No complete near-1M answer, preparation-time result, long-answer tokens/sec result or compaction result exists for N.**

All four captured allocator deltas were zero retries and zero OOMs **during that partial window only**. This does not establish full-context memory capacity. Serving-time compilation took 1.51–1.57 seconds on each rank; it may have contributed to latency, but it is not proven to be the sole cause. Total short-response latency is not a streaming tokens/sec measurement.

The original model source, image and specification were restored and read back, and the native route returned READY. The recorded 32-worker / 256 session-and-attachment-file before/after snapshots matched. No running kernels were observed in those snapshots; not every arbitrary workspace file was hashed. Owned fixtures, profile changes, temporary credentials and the long-request reservation were cleaned up.

| Earlier completed stages — trial M | Input / output tokens | Native time to first text | Native whole turn | Output stream tokens/sec |
| --- | --- | --- | --- | --- |
| 128K | 124,071 / 603 | 48.14 s | 56.28 s | 74.03 |
| 384K | 384,071 / 583 | 305.97 s | 313.65 s | 75.85 |

The near-1M stage stopped when each of the four GPUs recorded one allocation retry. There was no completed long answer or new compaction result; the candidate was rejected. These retries are distinct from an uncaught CUDA out-of-memory failure: the captured OOM counters remained zero.

Short requests remained responsive in that bounded run: **136/136** passed their recorded content checks with **zero retries**. The **86 replies recorded during near-1M preparation** had **4.28s median**, **6.48s p95**, and **9.40s maximum** native turn time. Numeric exact-match and prose content-band checks are different checks; these are measured samples, not a service guarantee.

The newer **N9 small GPU allocation test passed five BF16 numerical cases**, with zero maximum absolute difference, zero allocation retries and zero OOMs on the fixed path. It used synthetic metadata without loading model weights. It does not measure output tokens/sec, cold preparation, full-model near-1M stability or compaction; the subsequent full-model N test failed its short-request responsiveness gate. Its selected rounded allocation changed from 1,748 to 888 MiB in the synthetic test, not total model VRAM.

The 21 October run also recorded a **158.04 tokens/sec median across 50 short numeric streams**, 49 of which completed entirely within the concurrent long turn. That is a short-output result, not the speed of its long prose answer. Likewise, the earlier four-client **117.75 tokens/sec combined** result is aggregate throughput, not 100+ per conversation. Cold preparation, answer streaming, full-turn latency and aggregate throughput must remain separate.

The restored **18:16 ICT snapshot** records **SGLang on four H100s**, not DeepInfer: memory fraction **0.922**, prefill **1,024 / 1,024 tokens**, a **1,048,576-token ceiling** and **a backend running-request cap of 8**. The long-input policy admits **one above-128K request at a time**, leaving shorter work concurrent; this does not qualify two simultaneous maximum-context requests.

Earlier compaction passed on the **21 October profile**, from **948,102 source tokens**: summary **393.12s**, continuation **388.90s**; **23 short replies** had **6.04s median / 10.06s maximum**. Cancellation took **0.024s**, the reference was recalled after process replacement, and the recorded original/history replacement hashes matched. This is preserved historical acceptance, not requalification of the latest candidate. The 384K scoped retrieval review also does not establish strict sentence-by-sentence citation adherence.
