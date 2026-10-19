## Latest implementation and qualification

**19 October 2026: the corrected 128 MiB score-tile profile passed the recorded DeepSeek-V4.1-Flash-1017 workloads on the existing four H100 NVL GPUs.** The checkpoint is pinned to revision `1bae0e1088993b9b82de08f59de5be5a34e42170`. Earlier checkpoint results and the first 1017 trial remain separate historical records.

| Setting | Qualified profile |
|---|---|
| Total context | 1,048,576 tokens, including output and reserve |
| Speculation | DSpark block 5 |
| Static memory | 0.923 |
| Active request / decode graph cap | 8 / 8 |
| Prefill chunk / maximum | 1,024 / 1,024 |
| Maximum prefill requests / prefix tails / decode interval | 2 / 16 / 4 |
| Attention-score tile / warm step | 128 MiB / 2,048 tokens |
| Long admission | One active request above 128K and one bounded FIFO waiter; ordinary requests bypass this queue |

### Measured results and their scope

| Actual DSH check | Recorded result |
|---|---|
| 256K | 257,688 input / 7 output; 147.06s; 12 short replies, median 3.58s |
| Cold near-1M | 1,007,752 input / 431 output; exact saved answer in **27m33.97s**; 149.15 stream tokens/sec |
| Short requests alongside cold work | **60/60** correct, saved and retry-free; paired median **5.11s**, including two eight-client bursts |
| Immediate cached continuation | 1,008,209 input / 1,199 output; **15.13s**, **159.22 stream tokens/sec**; exact, saved and retry-free |
| Real tool continuation | 1,009,686 input; **12.94s**; actual create/read/delete command, successful tool result and file absent before/after |
| Fresh ordinary concurrency | **31/31** replies across 1, 2, 4, 8 and 16 clients; cap eight means excess clients may queue |
| Structured 599-token replies | Three correct saved answers at **163.34–166.48 stream tokens/sec** |
| Managed clients | Ordinary Claude Code 2.1.301 reply 1.171s and TrueForge 0.179.2 reply 0.732s, saved; these are not fresh CLI 1M tests |
| History preservation | **167 histories / 188 original files / 20 main runtimes**: original IDs and bytes unchanged |
| Runtime failures | Zero retries, allocation mapping warnings, fatal signatures or model restarts in the final qualification |

The first 1017 trial returned the correct near-1M answer with 52 short replies, but eight recoverable allocation warnings failed its strict gate. Reducing the score tile from 256 to 128 MiB passed GPU mathematical equivalence before the final full rerun. A correct answer alone did not qualify the first profile.

Minimum free GPU memory observed at one-second NVML sampling was **38 MiB per GPU**; memory remains tight. This is not a continuous peak bound. An optional prose follow-up after burst traffic re-entered cold preparation and was cancelled. It provides no prose-quality acceptance and does not guarantee cache reuse after load. Keep it distinct from the passed immediate cached continuation. Streaming speed excludes cold preparation and is not an SLA or a claim that every task exceeds 100 tokens/sec.

| Fresh clients | Completion window | Combined cohort output tokens/sec |
|---|---|---:|
| 1 | 1.29s | 92.02 |
| 2 | 1.82s | 130.51 |
| 4 | 2.61–3.12s | 152.49 |
| 8 | 3.18–5.96s | 159.81 |
| 16 | 2.89–10.97s | 173.57 |

These are bounded workload-specific samples, not simultaneous full-1M capability for sixteen clients. Two full-1M requests are not admitted simultaneously. Saved original failed and cancelled cases remain part of the trial history. The checkpoint-specific [model update report](MODEL_UPDATE_1017.html) describes the rollout and qualification; the security companion stays focused on controlling the three risks.
