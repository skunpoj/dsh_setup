# DeepSeek-V4.1-Flash on 4× H100 NVL: plan, measured results and the DeepInfer SM90 track

## Current production (30 Oct 2026, UTC)

**DeepInfer + DSpark serves this node in production**, replacing SGLang (kept as the measured baseline and rollback). Full details, the configuration matrix and the fixes we needed: [DeepInfer#221, production update](https://github.com/deepseek-ai/DeepInfer/discussions/221#discussioncomment-19270514).

- **Expert exchange:** cross-socket GPU P2P drops writes on this host, so DeepEP is not used. Experts are exchanged over an NCCL all-to-all fallback (`DEEPINFER_EP_COMM_BACKEND=nccl`, `NCCL_P2P_LEVEL=NVL`).
- **Serving config:** 1M-token context, 2 sequences per rank (8 requests at once), 1,024-token prefill chunks, `--routing least-loaded`, DSpark on, `humming-kernels` 0.1.13.
- **Measured (512 output tokens):** 1 user 60.9 tok/s (TTFT 0.7 s). A burst of 8 simultaneous requests all start within 1.7 s and produce 313–347 tok/s in total. An 857K-token prompt was answered correctly in 273 s.

All numbers are output tokens per second with 512-token answers. "At once" is how many requests run together.

| Setup | Longest prompt | At once | 1 user | All users together | Status |
|---|---|---|---|---|---|
| SGLang + DSpark (before) | 1M | 8 | 68 | 126–145 at 16 users (first token 13.5–15.9 s) | measured, 30 Oct matched |
| DeepInfer, 128K (29 Oct) | 128K | 16 | 58 | 277 at 16 users | measured |
| **DeepInfer, 1M (now)** | **1M** | **8** | **61** | **313–347 at 8 users** | **measured** |
| DeepInfer after the host P2P fix | 1M | 8 | ~80–150 | ~1.3–2.5× today | estimate |

Fixing the host makes every step faster, but it does not raise the 8-at-once limit at 1M, which comes from KV memory.

**Matched comparison, 30 Oct** (same checkpoint, straight to each engine, temperature 0; per-user decode tok/s and total tok/s, medians of 3 runs):

| Workload | Clients | DeepInfer per user | DeepInfer total | SGLang per user | SGLang total |
|---|---|---|---|---|---|
| Essay, 512 tokens forced (W1) | 1 | 57.8 | 56 | 67.6 | 67 |
| Essay (W1) | 16 | 51.2 | 384 | 16.5 | 126 |
| Free text, up to 512 (W4) | 1 | 62.1 | 60 | 68.0 | 67 |
| Free text (W4) | 16 | 55.6 | 421 | 18.9 | 145 |
| "List the integers 1..40" (W3) | 1 | 162.5 | 117 | 166.9 | 142 |
| "List the integers 1..40" (W3) | 8 | 147.3 | 862 | 52.3 | 284 |

- **One user:** SGLang is about 9–17 % faster.
- **Many users:** DeepInfer is about 3× faster in total; SGLang's per-user speed falls to 16–19 tok/s at 8 or more clients.
- **The "1..40" prompt is not a general speed:** the 19 Oct "SGLang 149–166 tok/s" figure was measured on it; counting is so predictable that DSpark accepts most draft tokens. On ordinary text both engines run at 58–68 tok/s for one user.
- **Long context:** DeepInfer has no prefix cache yet. The first token takes 38.6 s at 127K, 145 s at 498K and 301 s at 995K tokens, and a follow-up turn is no faster.

> **Everything below is the plan and the measurements as of 28 Oct 2026, kept for history.** It describes SGLang as the serving engine and Path C as a plan; both are superseded by the section above.


Qualification correction (28 October): the performance tables are conditional scenarios, not validated H100 forecasts or hard ceilings. Direct #200 GPU scale storage raises the retained residency lower bound to about 85.40 GiB per GPU before runtime overhead. Humming 0.1.13 alone does not prove unchanged original FP4 values. Memory, precision, four-rank execution and recovery gates remain required; see [PERF_MODEL.md](PERF_MODEL.md#8-memory-and-precision-gates-precede-every-path-c-scenario).

Status: 28 October 2026. Discussion: [deepseek-ai/DeepInfer#221](https://github.com/deepseek-ai/DeepInfer/discussions/221).
**Decision, 28 Oct 2026: Path C (DeepInfer on H100) is the primary path.** Findings, decision tree and plan: [PATH_C.md](PATH_C.md). Step-by-step commands are in [RUNBOOK.md](RUNBOOK.md); how this folder is kept in sync is in [SYNC.md](SYNC.md).

Every number on this page is labelled **measured** (with date and method) or **projected** (an estimate that has not been run). Nothing projected should be quoted as a result.

## 1. Setup

| Item | Value |
| --- | --- |
| GPUs | 4× H100 NVL 94 GB (SM90). NVLink bridges pair GPU0↔GPU1 and GPU2↔GPU3; the two pairs talk over PCIe |
| Host memory | About 1 TiB |
| Model | `deepseek-ai/DeepSeek-V4.1-Flash-1017`, revision `1bae0e1088993b9b82de08f59de5be5a34e42170`; MXFP4 routed experts (about 276 GiB), FP8 Engram tables (about 189 GiB), FP8 attention, BF16 vision |
| Engine on 28 Oct (since replaced, see above) | SGLang, `--tp-size 4`, `--moe-runner-backend marlin`, DSpark speculative decoding (block size 5), Engram tables in host memory (`SGLANG_ENABLE_DSV41_ENGRAM_HOST_TABLE=1`), 1M-token context, `--max-running-requests 8`, `--cuda-graph-max-bs-decode 8` |

The full weights (about 475 GiB) do not fit in 4 × 94 GB of HBM. Engram tables therefore live in host memory, which every engine on this node has to support.

## 2. Measured today

**Measured 27–28 Oct 2026** with [`stream_bench.py`](../../scripts/v41_h100/stream_bench.py) straight to SGLang, DSpark on, 512 output tokens, `--ignore-eos`:

| Concurrency | Per-user decode tok/s (p50) | Aggregate tok/s | TTFT p50 (s) | TTFT p95 (s) |
| --- | --- | --- | --- | --- |
| 1 | 68.3 | 76.1 | 0.14 | 0.14 |
| 2 | 49.8 | 110.0 | 0.14 | 0.15 |
| 4 | 31.9 | 135.3 | 0.18 | 0.35 |
| 8 | 19.9 | 154.5 | 0.40 | 11.7 |
| 16 | 19.8 | 154.7 | 26.9 | 36.1 |
| 32 | 19.8 | 157.5 | 79.4 | 85.8 |

DSpark accept length in the server log: 3.3–4.6 tokens per verify step.

Caveats:

- `--ignore-eos` forces writing past the natural end and lowers acceptance. Per-workload runs without it are step A1 of the runbook.
- The node is shared. Other traffic may have been present during these runs; from A1 on, `stream_bench.py --metrics-url` records the server queue before and after every run.

What the numbers say:

1. **Above 8 users the limit is the 8-request cap; from 4 to 8 it is the speculative step.** From concurrency 8 up, extra requests only queue (TTFT 27 s at 16, 79 s at 32) while per-user speed stays at 19.8 tok/s. Between 4 and 8, aggregate already grows little (135 → 155 tok/s), see point 3. Raising the cap alone may therefore add little; turning speculation off at high concurrency is part of the same path.
2. **Per-user speed is limited by step time.** 68 tok/s ÷ 3.3–4.6 accepted tokens is 48–68 ms per verify step. 200 tok/s per user at the same acceptance needs 17–23 ms steps (2.5–3.5× faster). More speculation cannot close that gap; the step itself must get faster.
3. **The step grows steeply with batch under speculation.** Assuming similar acceptance, a verify step at concurrency 8 takes about 3.5× as long as at concurrency 1 (about 190 ms vs 55 ms; 8 requests × 5 draft tokens per step). That is why aggregate grows so little from 4 to 8.

## 3. Goal and what "200+ tok/s" means here

| Target | Definition | Status |
| --- | --- | --- |
| T1: 200+ aggregate | Total output tok/s across concurrent users ≥ 200, with TTFT p95 ≤ 5 s, no OOM, natural stopping | Not met: 155 measured |
| T1+: 300+ aggregate | Same, ≥ 300 | Not met |
| T2: 200 per user | One stream ≥ 200 tok/s p50 on code or JSON at concurrency 1, quality unchanged | Not met: 68 measured |

A single "200 tok/s" figure without workload and concurrency is meaningless on this setup.

## 4. Paths ranked by chance of success

Path C is the chosen primary path (see [PATH_C.md](PATH_C.md)); it has the lowest chance of running but the highest upside. Paths A and B are ranked here by chance and continue inside path C's maintenance windows.

Chances are our judgment from the measurements above, not measured results. Duration is elapsed time with the work done by coding agents. The limiting factor is GPU maintenance windows (each one takes the production service down), not writing code.

| Rank | Path | Uses DeepInfer? | Target it can reach | Chance (judgment) | Duration | Expected result (projected) |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | **A. SGLang capacity:** raise the running-request and CUDA-graph caps with a memory plan; turn speculation off at high concurrency | No | T1, probably T1+ | About 30–40% for T1 (revised by the step-time fit in [PERF_MODEL.md](PERF_MODEL.md): with speculation on, the unchanged linear model approaches 197 tok/s; 200+ in this unchanged-fit scenario needs speculation off and a per-request cost that scales with verified tokens). Low for T1+ | 1–2 weeks, 3–4 windows | Caps alone: 175–185 tok/s. Speculation off at 32–64 requests: 50–230 tok/s, 2–7 tok/s per user |
| 2 | **B. Profile, then port one SM90 kernel from DeepInfer into SGLang (E8)**, starting with the indexer, which falls back to torch on SM90 today | Yes: kernels from DeepInfer PRs #92/#148 | Faster steps; T2 only if several levers stack | Profile: near certain. Measurable gain: about 50%. T2: low (about 10–20%) | 2–4 weeks after A's first window | If the per-request cost is mostly the indexer: about 90 tok/s per user and 560–680 aggregate at 16–32; with the fixed cost also cut: 160–220 per user, 680–1,100 aggregate |
| 3 | **C. DeepInfer itself on 4× H100 NVL (E6)**, built from the #92 Hopper port | Yes: the whole engine | Correct serving on H100 first; speed unknown | Runs correctly: low (about 10–15% today; about 20–25% if CUDA P2P works across the pairs; about 40–50% if the first window's probes pass). Beats SGLang: unknown | 3–5 weeks (C-direct); 5–9 weeks if an NCCL expert-parallel backend must be written | If it runs (low confidence, derived in [PERF_MODEL.md](PERF_MODEL.md)): 115–205 tok/s per user at concurrency 1 (central 150); 1,200–2,700 tok/s aggregate at 16–32 concurrent with short contexts (central 1,550–2,100). #92 measured 209 tok/s at concurrency 1 and 2,285 at 32 on 4× H20-3e (141 GB, all weights on GPU, full NVLink) |

**Derived, not guessed:** our measurements fit step(b) = α + β·b almost exactly, with β ≈ 5.1 ms per running request per accepted token. That fitted per-request term gives an asymptote near 197 tok/s only under unchanged linear behavior and acceptance, and it is about 5× the per-request cost #92 shows on H20. Removing it (path B2, or path C, whose H100 cost structure remains to be measured) is the main lever for both single-user speed and capacity. Details: [PERF_MODEL.md](PERF_MODEL.md).

### What each step adds (projected)

Only the first row is measured. Every other number is a projection to be checked by measurement.

| Step | What it does | One user alone (tok/s) | Total across users (tok/s) | First-token wait at 16–32 users |
| --- | --- | --- | --- | --- |
| Today (measured) | SGLang + DSpark, 8-request cap | 68 | 155 | 27–80 s |
| A1 measure per workload | Honest per-workload numbers, natural stopping, idle server | Code/JSON likely above 68 | Same | Same |
| A2 memory plan | Safety gate for A3 | Same | Same | Same |
| A3 caps 16 → 32 | More users decode at once instead of queueing | Same | 175–185 under the unchanged-fit scenario (not a measured ceiling) | A few seconds |
| A4 speculation off at high concurrency | Plain decoding is more efficient at large batch | 68 if speculation can stay on for small batches; otherwise about 20–30 | 50–230, depending on how the per-request cost splits | A few seconds |
| B1 profile | Where step time goes (indexer, all-reduce, Engram copy, MoE, idle) | Same | Same | Same |
| B2 port the dominant SM90 operation from #92/#148 | Cuts the per-request cost (if it is the indexer) | About 90 | About 560–680 | Seconds |
| B3 further levers (communication, Engram layout, launch gaps) | Cuts the fixed per-step cost | About 160–220 | About 680–1,100 | Seconds |
| C DeepInfer on H100 | Correctness first, then a matched benchmark | 115–205 if it runs (central 150; scaled from #92's 209 on 4× H20-3e) | 1,200–2,700 with short contexts (central 1,550–2,100) | Seconds |

### Theoretical ceiling (rough bound, not a target)

Assuming DeepSeek-style routing (about 8 of 256 routed experts per token; confirm from the model's `config.json`):

| Bound | Reasoning | Estimate |
| --- | --- | --- |
| Per user, hardware ceiling | Active weights are about 2–4 GiB per GPU per token at 3.9 TB/s (about 1 ms); verifying 5 draft tokens touches more experts (about 2–4 ms); all-reduces across the PCIe link between the NVLink pairs add about 2–3 ms. Step floor about 4–7 ms at about 4 accepted tokens per step | About 550–1,000 tok/s |
| Per user, realistic best | Batch-1 decode with TP over PCIe usually reaches well under half the bandwidth roofline | About 150–300 tok/s |
| Aggregate, compute ceiling | About 40 GFLOP per token across 4 GPUs | Tens of thousands of tok/s; not the binding limit |
| Aggregate, realistic | Bounded by how many requests fit in KV memory next to a 1M-token context reservation | About 300–1,500 tok/s depending on context budget |

Today's 48–68 ms step is roughly 10× the floor, so most of it is overhead that can in principle be removed. B1 shows which overhead dominates.

### Gates for Path C (E6)

| Gate | Question | Pass condition |
| --- | --- | --- |
| G1 toolchain | Does #92 build for sm90 against this node's driver? | CPU build passes; driver is R590, or R570 with the CUDA 13 forward-compat library |
| G2 memory | Do weights + drafter + DeepEP buffers + KV + load-time repack fit in 94 GB per GPU at EP4 with Engram on host? | Steady state and load peak each leave ≥ 3 GiB per GPU. On paper, weights alone are about 79 GiB per GPU before drafter, KV, buffers and repack |
| G3 host Engram | Can #200's UVA fetch keep Engram in host memory inside an unprivileged container? | `/dev/shm` holds about 200 GiB and `cudaHostRegister` of it succeeds (`sm90_probes.py pin`) |
| G4 topology | Does DeepEP EP4 work without GIN when only GPU pairs share NVLink? | CUDA P2P across the pairs, NCCL load/store domain of 4 (`sm90_probes.py lsa`), and DeepEP `tests/ep/test_ep.py` passes on 4 GPUs; otherwise an NCCL expert-parallel backend (C-NCCL) |

Estimated chances and the code-level reasons are in [PATH_C.md](PATH_C.md) section 2. The decisive question is whether CUDA P2P works between the two NVLink pairs: without an RDMA NIC, DeepEP (`EP_DISABLE_GIN=1`) needs all four GPUs in one NCCL load/store domain, and #92 has no other expert-parallel path. Engram must use #200's host-memory UVA fetch, because the default Engram path needs GPU-initiated RDMA.

**Fail-fast order:** (1) no-window check that GPU peer-to-peer works across the two pairs (`nvidia-smi topo -p2p r`); if it does not, route C-NCCL or stop; (2) G1 build of #92 + #200; (3) one window for the probes, G3 and G4; (4) only then the load windows. Stop when the pairs cannot share one load/store domain and no NCCL expert-parallel backend will be built, memory is over budget after shrinking KV, `/dev/shm` or host-memory registration cannot be provided, or GSM8K is clearly worse than SGLang.

Settled on SM90 and not worth retrying: DeepEP's MXFP4 path asserts SM100/SM120; FP8 experts need about 551 GiB; a text-only mode does not unlock DeepEP.

## 5. Plan and timeline

All work is done by coding agents with one runtime executor for anything that touches the GPUs. The owner approves each window.

| Week | Work | GPU window | Output |
| --- | --- | --- | --- |
| 1 | C0 P2P check (no window). C1 build #92 + #200. C2 memory admission and trial pod with large `/dev/shm`. A1 per-workload matrix and A2 memory plan in parallel | None | Route chosen; G1/G2 verdicts; per-workload table |
| 1–2 | C3 window 1: probes, #92 suite, DeepEP EP4 without GIN, #200 UVA test; SGLang restart used for A3 (caps 16) | 1 window | First public H100 results for #92, pass or fail |
| 2–3 | C4 window 2: first load and offline generation; SGLang restart used for the B1 profile | 1 window | Memory, coherence, DSpark acceptance |
| 3–5 | C5 window 3: GSM8K and matched benchmark; SGLang restart used for A4. B2 port proceeds in parallel off-window | 1–2 windows | E6 verdict and matched table, including losing rows |
| +2–4 | Only if needed: C-NCCL expert-parallel backend, then C3/C4 again | 1–2 windows | Runs without full NVLink or RDMA |

Each result is posted to [#221](https://github.com/deepseek-ai/DeepInfer/discussions/221) when it is measured, including failures.

## 6. Relation to DeepInfer

| Work item | DeepInfer code it uses | What it gives back to DeepInfer | Status |
| --- | --- | --- | --- |
| Production today: SGLang + DSpark | None. SGLang's own V4.1 support (DSpark drafter, DeepSeek kernels, host Engram table) integrated by the SGLang team | The SGLang baseline for the matched comparison (same node, same prompts) | Running; measured |
| Path A: SGLang capacity changes | None | More baseline rows (higher caps, speculation off) | Planned in SGLang restarts |
| Path B: port one SM90 kernel into SGLang (expected: the sparse-attention indexer) | #92's `sm90_ops` indexer kernels (Triton/Gluon), with #148 as a second source | An H100 parity and speed data point for #92's kernels; a credited port that other SGLang-on-Hopper users can use | Waits on the one-step profile |
| Path C: DeepInfer itself on 4× H100 NVL | #92 (Hopper port) + #200 (UVA host Engram fetch) + #147 (OpenAI server), `humming-kernels` 0.1.13, DeepEP `93eb6eb` with `EP_DISABLE_GIN=1` | First public H100 test of #92; first Hopper test of #200; first test of DeepEP EP4 over a load/store domain spanning PCIe P2P; the smallest-memory EP4 configuration (94 GB per GPU); results JSONL for #92 and kabishou11/deepinfer-hopper | Primary; P2P check first |
| Path C fallback: NCCL expert-parallel backend | #92's `EPBuffer` call sites | An `EPBuffer`-compatible NCCL all-to-all path for Hopper nodes without full NVLink or RDMA (upstreamable) | Only if P2P across pairs fails |
| Earlier component work in #221 (24–25 Oct) | None (our own native path) | A same-host `SCM_RIGHTS` fd exchange for restricted containers; a shared-host raw lookup prototype (80/80 cases on 4× H100 NVL) | Superseded for Engram by #200's `/dev/shm` approach; the fd exchange is still offered |
| Tools: `run_matrix.sh`, `perf_model.py`, `sm90_probes.py` | None | Reusable benchmark, step-time model and topology probes for any SM90 DeepInfer bring-up | Published |

Positioning: today we run SGLang, not DeepInfer, and we have not ported DeepInfer. #47, #92, #148, #180 and #235 are the SM90 efforts; we build on #92 and #200. To our knowledge there is no public DeepInfer run on H100 yet. Earlier public H100 reports for V4.1 on other engines describe 40–50 tok/s and OOM ([SGLang #39791](https://github.com/sgl-project/sglang/discussions/39791)).

### What we claim, and what we do not

| Status | Claim (dated, "to our knowledge") |
| --- | --- |
| Now | A public report with reproduction artifacts of V4.1-Flash serving on 4× H100 NVL (SGLang + DSpark, Engram in host memory, 1M context), with open tools and measured numbers |
| Now | Public write-up of what does not work for V4.1 on SM90 (DeepEP MXFP4, FP8 experts, text-only mode) |
| Now | Component level only: shared-host raw lookup, 80/80 numerical cases on 4× H100 NVL |
| After window 1 (G3/G4) | Potential dated H100-specific report of #92's SM90 suite and DeepEP EP4 on H100 NVL with PCIe-joined pairs, pass or fail; a public test of #200's UVA Engram fetch on Hopper |
| After first correct load | Potential first-public H100 claim only after execution and a fresh prior-art search, with less than 141 GB per GPU and Engram in host memory, building on #92 and #200 |
| After matched benchmark | Dated same-node SGLang vs DeepInfer comparison on H100 NVL, including losing rows; Hopper comparisons already exist ([SGLang #46310](https://github.com/sgl-project/sglang/issues/46310)) |
| Never | First DeepInfer port to SM90 or Hopper; first V4.1 serving on Hopper; "we ported DeepInfer"; any unmeasured tok/s |

## 7. Files

| Path | Purpose |
| --- | --- |
| [`scripts/v41_h100/stream_bench.py`](../../scripts/v41_h100/stream_bench.py) | Per-user streaming benchmark: TTFT, decode tok/s, aggregate, server queue state |
| [`scripts/v41_h100/run_matrix.sh`](../../scripts/v41_h100/run_matrix.sh) | Workload × concurrency matrix, identical for every engine |
| [`scripts/v41_h100/parse_decode_log.py`](../../scripts/v41_h100/parse_decode_log.py) | Accept length and step time per batch size from SGLang decode logs |
| [`scripts/v41_h100/bucket_trace.py`](../../scripts/v41_h100/bucket_trace.py) | GPU time per kernel bucket from a torch-profiler trace |
| [`scripts/v41_h100/allreduce_lat.py`](../../scripts/v41_h100/allreduce_lat.py) | All-reduce latency at decode-sized messages |
| [`scripts/v41_h100/ckpt_admission.py`](../../scripts/v41_h100/ckpt_admission.py) | Per-GPU weight bytes from safetensors headers (no tensor reads) |
| [`scripts/v41_h100/deepinfer_sm90.sh`](../../scripts/v41_h100/deepinfer_sm90.sh) | DeepInfer #92 + #200 fetch and merge, sm90 build, probes, tests, first offline load |
| [`scripts/v41_h100/perf_model.py`](../../scripts/v41_h100/perf_model.py) | Step-time model that derives every projected tok/s figure ([PERF_MODEL.md](PERF_MODEL.md)) |
| [`scripts/v41_h100/sm90_probes.py`](../../scripts/v41_h100/sm90_probes.py) | CUDA P2P matrix, NCCL load/store domain size seen by DeepEP, `/dev/shm` + `cudaHostRegister` probe |
| [`docs/deepseek-v41-h100/PATH_C.md`](PATH_C.md) | Path C findings, gates, decision tree, plan and claims |
| [`scripts/v41_h100/workloads/`](../../scripts/v41_h100/workloads/) | Synthetic prompts: code, JSON, maths, English and Thai chat |

## 8. References

DeepInfer pull requests and discussions this work builds on or relates to:

- [#47](https://github.com/deepseek-ai/DeepInfer/pull/47) (sicnuyudidi): RFC, SM90 (H20-3E) support.
- [#92](https://github.com/deepseek-ai/DeepInfer/pull/92) (DarkraiHL): SM90 (Hopper) support, V4.1-Flash end to end on 8×/4× H20-3e. Our base for path C.
- [#148](https://github.com/deepseek-ai/DeepInfer/pull/148) (yuyu5333): SM90 kernels for H100/H200/H20, validated on 8× H20.
- [#180](https://github.com/deepseek-ai/DeepInfer/pull/180) and [#235](https://github.com/deepseek-ai/DeepInfer/pull/235) (tonyh168): SM90 platform support for V4.1 on H20, and SM90 sparse MLA on Triton with a reproducible H20 image.
- [#88](https://github.com/deepseek-ai/DeepInfer/pull/88), [#91](https://github.com/deepseek-ai/DeepInfer/pull/91), [#101](https://github.com/deepseek-ai/DeepInfer/pull/101) (JianWang97): SM90 BF16 TFLOPS limits, and the MXFP4 → FP8 expert conversion and loader. FP8 experts double expert memory, which is why we stay on FP4 experts at 94 GB per GPU.
- [#200](https://github.com/deepseek-ai/DeepInfer/pull/200) (JohnQin-llm): opt-in UVA Engram fetch for single-node deployments (tested on B200/B300). Required for path C on a node without an RDMA NIC.
- [#99](https://github.com/deepseek-ai/DeepInfer/pull/99): NVLink Engram fetch (one all_to_all per step), the other GIN-free option; #200 measured its decode slower than the default path because its buffers are sized for prefill.
- [#147](https://github.com/deepseek-ai/DeepInfer/pull/147) (kzjeef): minimal OpenAI-compatible server over the offline engine, used for the matched benchmark.
- [#238](https://github.com/deepseek-ai/DeepInfer/discussions/238): question on official H200 (SM90) support.

Libraries and forks:

- [DeepEP](https://github.com/deepseek-ai/DeepEP), [DeepGEMM](https://github.com/deepseek-ai/DeepGEMM), [FlashMLA](https://github.com/deepseek-ai/FlashMLA): DeepEP intranode is gate G4; DeepGEMM's FP8×FP4 MQA-logits kernels need SM100+, so SGLang's indexer falls back to torch on SM90; [#92](https://github.com/deepseek-ai/DeepInfer/pull/92) builds FlashMLA's SM90 path.
- [humming](https://github.com/vllm-project/humming) ([`humming-kernels` on PyPI](https://pypi.org/project/humming-kernels/)): the W4A8 MoE backend [#92](https://github.com/deepseek-ai/DeepInfer/pull/92) uses on SM90. We pin 0.1.13: LunarFeller reported a misaligned read in 0.1.12 on H200 (comment on #92), fixed upstream in 0.1.13. [kabishou11/deepinfer-hopper](https://github.com/kabishou11/deepinfer-hopper) maintains #92 as a Hopper-first fork with untested H100/H200 layouts and the same pin.

Model and other engines:

- [deepseek-ai/DeepSeek-V4.1-Flash-1017](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017), revision `1bae0e1088993b9b82de08f59de5be5a34e42170`.
- [SGLang cookbook: DeepSeek-V4.1](https://docs.sglang.io/cookbook/autoregressive/DeepSeek/DeepSeek-V4_1): our serving baseline (preview build with DSpark); lists H200, B200, B300, GB300 and MI355X, not H100.
- [SGLang discussion #39791](https://github.com/sgl-project/sglang/discussions/39791): earlier public V4.1-Flash on H100 reports (about 40–50 tok/s single request, OOM at larger prompts or two parallel requests).

Our code, plan and measurements: [skunpoj/dsh_setup → docs/deepseek-v41-h100](https://github.com/skunpoj/dsh_setup/tree/main/docs/deepseek-v41-h100) and [scripts/v41_h100](https://github.com/skunpoj/dsh_setup/tree/main/scripts/v41_h100).
