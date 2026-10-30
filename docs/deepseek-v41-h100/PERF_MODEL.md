# Expected tok/s, derived: a step-time model for V4.1-Flash on 4× H100 NVL

> **Outdated (30 Oct 2026, UTC): kept for history.** DeepInfer + DSpark has served production on this node since 29 Oct over the NCCL expert-exchange fallback. Current configuration and measured numbers: [Current production](README.md#current-production-30-oct-2026-utc) and [DeepInfer#221](https://github.com/deepseek-ai/DeepInfer/discussions/221#discussioncomment-19270514).

Status: 28 October 2026. Reproduce every number with `python3 scripts/v41_h100/perf_model.py`. Only the inputs in section 1 are reported measurements; everything else is a conditional scenario. The calculations do not establish hardware ceilings, success probabilities, H100 performance, or runtime admission.

## 1. Inputs

| ID | Source | Values |
| --- | --- | --- |
| M1 | Our SGLang + DSpark runs, 27–28 Oct 2026 (TP4, Marlin MXFP4, DSpark block 5, `--ignore-eos`, 512 output tokens) | Per-user decode tok/s: 68.3 (1 request), 49.8 (2), 31.9 (4), 19.9 (8). Aggregate plateau about 155 from 8 requests (cap 8). Accept length 3.3–4.6 |
| M2 | DeepInfer #92 on 4× H20-3e (DP4 × EP4, DSpark on, random ids, 1024 in / 512 out, closed loop) | 209 tok/s at concurrency 1; 2,285 total at 32; 2,959 total at 64 |
| M3 | Checkpoint headers and #92's docs | 384 routed experts per layer, top-6, hidden 5120, expert intermediate 2304, MXFP4 experts (about 18.8 MB per expert with scales), 40 main MoE layers plus one drafter MoE layer, attention FP8 5.2 GiB, shared/dense about 4.4 GiB |
| HW | NVIDIA specs | H100 NVL 3.9 TB/s HBM; H20-3e 4.0 TB/s; we assume decode kernels reach 75% of spec bandwidth |

## 2. The core relation

With speculative decoding, each verify step emits `a` accepted tokens per running request (a = accept length):

- per-user tok/s = a / step(b)
- aggregate tok/s = a · b / step(b), where b = running requests

So everything follows from how the step time grows with b.

## 3. Analytical traffic estimate (assumed routing and bandwidth)

Assuming uniform independent expert choices, b requests × 5 verify tokens × top-6 give an expected distinct-expert count per layer of 384 · (1 − (1 − 1/384)^(30·b)):

| Verify tokens per step | Distinct experts per layer | TP4 bytes per GPU | TP4 estimated traffic time | DP4 × EP4 bytes per GPU | DP4 × EP4 estimated traffic time |
| --- | --- | --- | --- | --- | --- |
| 5 (1 request) | 28.9 | 8.3 GB | 2.9 ms | 17.0 GB | 5.8 ms |
| 40 (8 requests) | 178.6 | 36.5 GB | 12.5 ms | 45.2 GB | 15.5 ms |
| 160 (32 requests) | 352.6 | 69.2 GB | 23.7 ms | 77.9 GB | 26.6 ms |

TP4 adds 2 all-reduces per layer across the PCIe link between our NVLink pairs, about 2–3 ms. Under these routing, bandwidth and communication assumptions, the traffic estimate at one request is about 4–6 ms. It is not a strict physical latency floor: routing locality, cache reuse, draft/verification work and overlapping operations need measurement. The gap from the reported 48–68 ms does not by itself identify removable software overhead or establish a 550–1,000 tok/s ceiling.

## 4. What our measurements say about SGLang's step

Fitting step(b) = α + β·b to M1 (step = a / per-user tok/s) gives an almost perfect line (largest residual ≤ 4.6 ms):

| Accept a | α (fixed per step) | β (per running request) | Conditional model asymptote a/β |
| --- | --- | --- | --- |
| 3.3 | 33.1 ms | 16.8 ms | 197 tok/s |
| 3.9 | 39.1 ms | 19.8 ms | 197 tok/s |
| 4.6 | 46.2 ms | 23.4 ms | 197 tok/s |

Two observations within this fitted model, assuming a common acceptance value across the four points:

1. **Every running request adds about 5.1 ms of step time per accepted token** (β/a). This fitted slope does not isolate a kernel or prove an overhead source. Candidates include indexer work, host Engram fetches, speculative work, scheduling and memory behavior. Engine-level timing and the B1 profile must distinguish them.
2. **The extrapolated linear model approaches about 197 tok/s only if its slope and acceptance remain valid beyond the measured concurrency range.** This is not a measured maximum for the build; batching behavior may change at 16 or 32 requests.

## 5. Projections by path

### Path A (SGLang configuration only)

| Step | Formula | Projection |
| --- | --- | --- |
| A3: cap 8 → 16 → 32, speculation on | a·b / (α + β·b) | 158 → **175 → 185 tok/s**; below 200 in this unchanged-fit scenario (asymptote 197) |
| A4: speculation off at high load | b / (α_off + β_off·b), one token per request per step | Depends on whether β scales with verified tokens: if it does (β_off ≈ β/5), **about 210 at 32 and 230 at 64 requests**, 6–7 tok/s per user; if only half does, about 110; if β is per request regardless, about 50 |

Revised chance of 200+ aggregate on path A alone: **about 30–40%** (it needs the A4 favourable case). Earlier estimates of 60–70% did not account for the per-request term.

### Path B (port DeepInfer's SM90 kernels into SGLang)

| Scenario | α | β | One user | Aggregate at 8 / 16 / 32 |
| --- | --- | --- | --- | --- |
| Today (fit) | 39 ms | 19.8 ms | 66 | 158 / 175 / 185 |
| B2: per-request term cut to DeepInfer-like level | 39 ms | 4.5 ms | **89** | 415 / 561 / 681 |
| B2 + B3: fixed term also cut | 20 ms | 4.5 ms | **159** | 557 / 678 / 761 |
| B2 + B3, best case | 15 ms | 3 ms | **217** | 800 / 990 / 1,124 |

The per-request β of #92 on H20 (section 6) shows what a per-request cost of about 4 ms looks like on SM90. If the B1 profile shows β is mostly the torch indexer, B2 alone is the largest single gain available on SGLang, for both single-user speed and capacity.

### Path C (DeepInfer #92 + #200 on our node)

Fitting #92's M2 numbers the same way (accept 3.5 assumed, DP4 so b_rank = concurrency / 4) gives **step(b_rank) ≈ 14.5 ms + 3.9 ms · b_rank** on H20. To move it to our node:

- hardware factor 0.80–1.05 (same memory bandwidth; H100 has about 5× the compute of H20, which helps the compute-bound parts);
- plus EP dispatch/combine latency over PCIe P2P between the pairs: 80 operations per step, adding 2–10 ms;
- illustrative EP traffic: 5 tokens × 6 experts × half remote × 15 KB × 40 layers gives about 9 MB per request per step. The code applies its coefficient to rank-local batch (concurrency / 4); it does not account for all ranks sharing the cross-pair link. The link scope, payload format, dispatch/combine counts and contention must be measured before interpreting these totals;
- the illustrative model omits additional Engram UVA decode time. #200's reported performance on other hardware does not establish negligible cost on H100 NVL; host NUMA placement, registration, PCIe contention and actual fetch latency require qualification.

| Case | One user | 16 users: per user / total | 32 users: per user / total |
| --- | --- | --- | --- |
| Optimistic | 205 | 127 / 2,030 | 84 / 2,695 |
| Central | **151** | **97 / 1,552** | **66 / 2,099** |
| Pessimistic | 116 | 77 / 1,236 | 54 / 1,714 |

Conditions: P2P across the pairs works, DeepEP EP4 runs with GIN off, memory fits with enough KV for 16–32 short requests per node, and real-prompt acceptance is close to #92's random-id runs. If DeepEP's load/store kernels turn out much slower over cross-socket PCIe than assumed, the EP terms grow and the totals fall accordingly; window 1's DeepEP test measures this directly.

## 6. Side by side (projections; today measured)

| | One user | Total at 16–32 users | Chance it happens |
| --- | --- | --- | --- |
| Today, SGLang (measured) | 68 | 155 (cap 8) | — |
| A3 caps only | 68 | 175–185 | Untested; unchanged-fit scenario below 200 |
| A4 speculation off at load | 20–68 (68 only if switchable by batch size) | 50–230 | 30–40% for 200+ |
| B2 indexer port | about 90 | 560–680 | about 50% that β is mostly the indexer |
| B2 + B3 | 160–220 | 680–1,100 | 10–20% |
| C DeepInfer on H100 | 115–205 (central 150) | 1,200–2,700 (central 1,550–2,100) | 10–15% today; 40–50% if window 1 passes |

## 7. How each number gets checked

| Projection | Measurement that confirms or refutes it |
| --- | --- |
| β per request, and what it is | A1 engine log (`parse_decode_log.py`: est_step_ms per batch size) and the B1 profile (`bucket_trace.py`) |
| A3 linear extrapolation near 197 | A3 run at 16 and 32 |
| A4 range | A4 run; also B1's split of β into per-token and per-request parts |
| Path C EP terms | Window 1: DeepEP `test_ep.py` timings on 4 GPUs without GIN, and `sm90_probes.py p2p` copy GB/s across the pairs |
| Path C totals | Window 3 matched benchmark |

## 8. Memory and precision gates precede every Path C scenario

The reviewed direct #200 path retains GPU copies of the Engram scales. The retained preflight estimate adds 6,144,186,368 bytes per rank to 85,551,717,192 bytes of resident weights: 91,695,903,560 bytes, about 85.40 GiB per GPU, before KV, DSpark state, JIT/graphs, allocator, communication and transient workspace costs. Against the saved 95,830 MiB total capacity this leaves about 8.19 GiB of total capacity, not actual free memory or an admission result. A different scale-placement path needs its own storage, kernel and memory proof.

Host source shards and new shared mappings can coexist during load. Registration, completion, unregister failure handling and recovery also need actual bounded validation. Humming 0.1.13 fixes an alignment issue but still contains conditional rescaling logic; the version pin alone does not establish unchanged original FP4 values. A complete scale audit and the exact numeric conversion or an independently qualified original-weight kernel are required. None of the scenario tables authorizes conversion or a full-model load.

All percentage chances and multi-week durations in related planning documents are judgments, not calibrated predictions or required waiting periods. The execution plan can target an earlier bounded trial without weakening these gates.

Actual scale-audit checkpoint, 28 October 2026 at 11:28:50 UTC: the read-only CPU audit completed all 47,232 scale tensors, 31,488 matrix groups and 17,411,604,480 scale-payload bytes. It found 33,731 clamp decisions in 28 groups. This is not proof of changed nonzero weights: the audit read no packed FP4 weight payload. The affected original packed values and exact conversion must be compared before accepting or rejecting numeric preservation for those groups. No GPU, full-model or DSpark acceptance follows from this result.
