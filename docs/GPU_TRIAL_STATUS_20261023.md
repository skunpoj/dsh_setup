# GPU performance and near-1M results

## GPU performance and 1M operation — 23 October 2026

**The latest optimization has not qualified 100+ output tokens/sec for a substantial near-1M conversation.** The last completed cold actual-DSH prose measurement used **1,008,049 input / 540 output tokens**, with **28m32.25s preparation** and **66.00 streaming output tokens/sec**. Generation speed excludes preparation; its whole-turn output rate was **0.31 tokens/sec**.

### Latest full-model trial N — stopped at the responsiveness limit

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
