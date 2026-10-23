# GPU performance and near-1M results

## GPU performance and 1M operation — 23 October 2026

**The latest actual DSH near-1M request completed:** **1,002,051 input / 636 output tokens**, **29m26.56s preparation**, **29m32.09s to first text**, **29m44.28s client elapsed**, and **61.56 streaming output tokens/sec**. The streaming rate excludes initial preparation. Preparation is measured at the forwarding boundary; time to first text also includes tokenization and forwarding overhead. **100+ tokens/sec per near-1M conversation has not been reached.**

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
