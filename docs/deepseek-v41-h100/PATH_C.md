# Path C: DeepInfer on 4× H100 NVL — findings, plan and decision tree

> **Outdated (30 Oct 2026, UTC): kept for history.** DeepInfer + DSpark has served production on this node since 29 Oct over the NCCL expert-exchange fallback. Current configuration and measured numbers: [Current production](README.md#current-production-30-oct-2026-utc) and [DeepInfer#221](https://github.com/deepseek-ai/DeepInfer/discussions/221#discussioncomment-19270514).

Status: 28 October 2026. **Path C is the chosen primary path.** Paths A and B continue only where they reuse the same maintenance windows (section 6).

Everything here comes from reading the code and pull requests on 28 Oct 2026: DeepInfer [#92](https://github.com/deepseek-ai/DeepInfer/pull/92) at `e205d42`, [#200](https://github.com/deepseek-ai/DeepInfer/pull/200) at `c1aa748`, [#180](https://github.com/deepseek-ai/DeepInfer/pull/180), [#235](https://github.com/deepseek-ai/DeepInfer/pull/235), DeepEP at `93eb6eb` (the commit #92 vendors), the [kabishou11/deepinfer-hopper](https://github.com/kabishou11/deepinfer-hopper) fork, and the NCCL device API documentation. Nothing below has been run on our hardware yet.

## 0. Verdict (28 Oct 2026, late): is path C the fastest, and is it feasible?

Qualification correction: the throughput ranges below are model scenarios, not validated H100 forecasts. The direct #200 route also keeps replicated GPU Engram scales; the retained residency lower bound becomes about 85.40 GiB per GPU before runtime costs, not a complete memory fit. See [PERF_MODEL.md](PERF_MODEL.md#8-memory-and-precision-gates-precede-every-path-c-scenario). No FP8 conversion or requantization is authorized by this plan.

| Question | Answer | Basis |
| --- | --- | --- |
| Fastest if it works? | **Highest total in the illustrative model; not established on this node** | Derived projections ([PERF_MODEL.md](PERF_MODEL.md)): C 115–205 tok/s per user (central 150) and 1,200–2,700 total at 16–32 users; B2+B3 160–220 per user but at most about 1,100 total; A at most about 230 total |
| Fits the hardware? | **Not yet established** | The direct #200 path adds about 5.72 GiB per rank of GPU Engram scales to the retained weight floor, giving about 85.40 GiB before KV, DSpark, graphs/JIT, communication, allocator and transient costs. The saved 93.58 GiB total capacity is not actual free memory. Host source/shared-map coexistence, registration and recovery need independent bounds. |
| Feasible with today's code? | **Not yet established** | #92 (Hopper port) is open and will not be merged upstream, so we would maintain it; #200 is open; they merge cleanly. DeepEP over PCIe P2P between NVLink pairs is untested upstream. No new SM90/H100 pull requests between #226 and #244 (checked 28 Oct) |
| Communication gate | **Actual DeepEP dispatch/combine across both NVLink pairs** | Driver P2P read/write capability is a preliminary check; actual kernels and bounded memory/lifecycle qualification are still required. |
| Planning estimate, not a required wait | **3–5 weeks** to a matched benchmark (route C-direct); **+2–4 weeks** if an NCCL expert-parallel backend is needed; production adoption (server, vision, operations) is a further decision after that | Section 4 |
| Uncalibrated judgment | **10–15% today; 20–25% if P2P works; 40–50% if window 1 passes** | These percentages are opinions, not measured probabilities or execution gates. |

Path C has the highest modeled upside under the stated assumptions; actual H100 results may rank the paths differently. C0 is an initial read-only capability check, not proof that DeepEP works across the pairs. A bounded C3 window can proceed only after the independent execution gates pass. Keep path B's one-step profile (B1) as the hedge: it runs in an SGLang restart that path C's windows already require.

## 1. Findings that change the plan

| # | Finding | Source | Consequence |
| --- | --- | --- | --- |
| F1 | DeepInfer's default Engram path is DeepEP's `EngramBuffer` with CPU storage fetched by **NCCL GIN (GPU-initiated RDMA)**. It needs an RDMA NIC | #92 `userbuffer.py` (`use_cpu_rdma_storage`), #180 ("Engram reads via NCCL GIN"), #200 | Our container has no RDMA device, so the default Engram path cannot start |
| F2 | **#200 replaces it** with `DEEPINFER_ENGRAM_UVA_FETCH=1`: the tables go into `/dev/shm` (about 196 GB), are registered with `cudaHostRegister`, and each GPU reads rows over its own PCIe link. No NIC, no collective per step. On 8× B200 it reached 91–99% of the official decode curve | #200 | Path C needs **#92 + #200**. They merge cleanly (checked 28 Oct). The container needs a `/dev/shm` of at least about 200 GiB, and host memory peaks at about 380 GB during load |
| F3 | DeepEP's `EPBuffer` initialises NCCL GIN unless **`EP_DISABLE_GIN=1`**. Without GIN, every EP rank must be in one NCCL **LSA (load/store accessible) team** | DeepEP `csrc/kernels/comm/context.cpp`, README | EP4 with no NIC works only if all four GPUs are one LSA team |
| F4 | NCCL's LSA team includes PCIe-connected GPUs **if they have CUDA P2P access** to each other; NCCL ≥ 2.28.4 no longer applies the `NCCL_P2P_LEVEL` distance check. #92 uses NCCL 2.32.3 | NCCL device API docs | The decisive question is whether CUDA P2P works between our two NVLink pairs (`SYS` in `nvidia-smi topo -m`). One read-only command answers it |
| F5 | DeepEP's own README states "NVLink for intranode communication" as a requirement and lists "PCIe kernel support for non-NVLink environments" as future work. Its NVLink check asserts only for GPUs whose name contains `PCIE`; an H100 NVL reports `NVIDIA H100 NVL` and passes that check | DeepEP README, `deep_ep/utils/envs.py` | Running DeepEP's load/store kernels over PCIe P2P between pairs is untested upstream. It may work slowly, or fail |
| F6 | MoE expert parallelism in #92 goes only through DeepEP `EPBuffer.dispatch/combine`; there is no NCCL all-to-all fallback. EP2 inside one pair cannot hold the experts (about 138 GiB per GPU) | #92 `mlp.py`, `userbuffer.py` | If P2P between pairs is not available, Path C needs a new NCCL all-to-all EP backend (section 4, route C-NCCL) |
| F7 | #92 measured **209 tok/s at concurrency 1** (TPOT 4.8 ms), 2,285 tok/s at 32 and 2,959 tok/s at 64 on **4× H20-3e** (DP4 × EP4, DSpark on, random token ids, 1024 in / 512 out; all weights on GPU, full NVLink). GSM8K 0.941 | #92 | If Path C runs here, it is the only path with SM90 evidence near 200 tok/s per user. Our differences: Engram over PCIe from host, EP traffic across PCIe between pairs, less memory |
| F8 | #92 sets `DEEPINFER_USE_NEXTN_DECODE` (DSpark) to **5 by default**. "DSpark off" needs `=0` explicitly | #92 `environ.py` | Fixed in our helper script |
| F9 | Routed experts stay MXFP4 with the `humming` backend: about 69 GiB per GPU at EP4. FP8-upcast backends need about 130 GiB per GPU and fit only at EP8. #180/#235 requantize experts to FP8 and target 8× H20 | #92 `doc/sm90.md`, #180 | Humming is a candidate within the memory envelope, not proven original-weight qualification. Version 0.1.13 retains conditional rescaling logic, so the full audit and numeric conversion proof remain required. Pin `humming-kernels==0.1.13` for the alignment fix: 0.1.12 has a misaligned read found on H200 (reported by LunarFeller on #92, fixed upstream in 0.1.13) |
| F10 | Others are converging on H100/H200: kabishou11's fork ships untested H100 layouts (80 GB SXM; EP4 called "tight or OOM"), and another team is validating #92 on H200. Neither has posted H100/H200 throughput | #92 comments, the fork's `doc/h100.md` | A "first public H100 result" is a race measured in weeks. Coordinate and credit rather than compete: fit on our 94 GB NVL devices remains subject to the complete memory proof |

## 2. Gates and estimated chances (judgment, not measurement)

| Gate | Question | How it is decided | Chance |
| --- | --- | --- | --- |
| **C0 P2P** | Can GPU0/1 reach GPU2/3 with CUDA P2P? | `nvidia-smi topo -p2p r` (read-only, no window) | 30–50% (cross-socket P2P is often disabled) |
| G1 build | #92 + #200 builds for sm90 on our driver | `deepinfer_sm90.sh fetch build collect` (no GPU) | About 85% |
| G2 memory | Experts about 69 GiB + replicated weights about 10 GiB + drafter + EP buffer + KV + repack peak fit in 93.6 GiB per GPU | `ckpt_admission.py` plus the code study, then the first load | 55–70% with short contexts |
| G3 host Engram | `/dev/shm` ≥ 200 GiB in the container and `cudaHostRegister` of it succeeds | `sm90_probes.py pin --gib 8`, then `--gib 200`, in the first window | About 75%, needs the container change approved |
| G4 EP | DeepEP EP4 dispatch/combine works with `EP_DISABLE_GIN=1` across the pairs | `sm90_probes.py lsa` (expect `nvl_ranks=4`) and DeepEP `tests/ep/test_ep.py`, first window | About 70% if C0 passes |
| G5 correctness | Coherent output, GSM8K subset within about ±2 points of SGLang | Second and third windows | About 75% once loaded |

End to end: about **10–15%** today; **about 20–25% if C0 passes**; **about 40–50% if the first window's probes all pass**.

If it runs (low confidence; derivation in [PERF_MODEL.md](PERF_MODEL.md) section 5): **115–205 tok/s per user at concurrency 1 (central 150)**; **1,200–2,700 tok/s aggregate at 16–32 concurrent with short contexts (central 1,550–2,100)**, if KV memory admits that many requests. 1M-token context under DeepInfer on this node is unlikely.

## 3. Decision tree

```
C0  nvidia-smi topo -p2p r across the pairs
 ├─ OK  ──► route C-direct: #92 + #200, EP_DISABLE_GIN=1, DeepEP over NVLink + PCIe P2P
 │          window 1: probes (p2p, lsa, pin) + #92 suite + DeepEP test_ep 4 GPUs + #200 UVA test
 │           ├─ all pass ──► window 2: first load (DSpark off, then on) ──► window 3: GSM8K + matched benchmark
 │           └─ lsa=2 or test_ep fails ──► route C-NCCL (below) or stop
 └─ NS/not OK ──► route C-NCCL: an EPBuffer-compatible expert-parallel backend on NCCL all_to_all
                  (2–4 weeks of backend work; performance unknown; a real upstream contribution), or stop
```

Stop when: the probes show `nvl_ranks=2` and no one will build route C-NCCL; memory does not fit after shrinking KV; `/dev/shm` or host-memory registration cannot be provided; or GSM8K is clearly worse than SGLang.

## 4. Steps (commands in [RUNBOOK.md](RUNBOOK.md), path C)

| Step | Owner role | Window | Duration | Output |
| --- | --- | --- | --- | --- |
| C0 P2P check | Runtime executor | No | Minutes | `topo -p2p r/w` matrix; route chosen |
| C1 fetch #92 + #200, build, collect | Backend agent | No | 2–4 days | Build log, 179 tests collected, commit hashes |
| C2 code study and memory admission; trial pod spec with `/dev/shm` ≥ 200 GiB, host memory ≥ 450 GiB, no RDMA | Backend agent; reviewers | No | 3–5 days | Per-GPU admission table; reviewed manifest |
| C3 window 1: `deepinfer_sm90.sh probes` then `gpu-tests` | Runtime executor | Yes, about 60 min | 1 window | Probe results, #92 suite N/162, DeepEP EP4 result, #200 UVA test |
| C4 window 2: `deepinfer_sm90.sh offline` | Runtime executor | Yes, about 90 min | 1 window | Peak/steady GPU memory, host memory, coherent output, DSpark acceptance |
| C5 window 3: GSM8K 200 on both engines; #147 server; `run_matrix.sh` against SGLang (no spec), SGLang + DSpark, DeepInfer + DSpark | Runtime executor | Yes, 90–120 min | 1–2 windows | Matched table, including rows where DeepInfer loses |
| C-NCCL (only if needed) | Backend agent; reviewers | No, then one window | 2–4 weeks | `EPBuffer`-compatible dispatch/combine over `torch.distributed.all_to_all_single`; parity tests against DeepEP on one NVLink pair |

Elapsed time: about **3–5 weeks** on route C-direct; add **2–4 weeks** for route C-NCCL.

## 5. What we can claim at each step

| After | Claim (dated, "to our knowledge", crediting #92, #148, #200, #47) |
| --- | --- |
| C0 | Nothing yet (a fact about our node) |
| C3 | Potential dated H100-specific report of #92's SM90 suite and DeepEP EP4 on H100 NVL with PCIe-joined pairs, pass or fail; a public test of #200's UVA Engram fetch on Hopper (#200 was tested on B200/B300) |
| C4 | Potential first-public claim, subject to a fresh prior-art search, for DeepInfer on H100 and an EP4 run with less than 141 GB per GPU and Engram in host memory |
| C5 | Dated same-node SGLang vs DeepInfer comparison on H100; any priority claim requires a fresh search |
| C-NCCL merged | An NCCL expert-parallel backend that lets DeepInfer run on Hopper nodes without full NVLink or RDMA |

## 6. Reusing the same windows for paths A and B

Each path C window ends by restarting SGLang. Use that restart for exactly one SGLang change and measure it before the window closes:

1. After C3: the B1 profile (`SGLANG_TORCH_PROFILER_DIR` set) on the unchanged profile. The step-time fit in [PERF_MODEL.md](PERF_MODEL.md) shows a per-request cost of about 5 ms per accepted token whose linear extrapolation approaches 197 tok/s only if acceptance and slope remain unchanged; B1 must determine the actual contributors.
2. After C4: A3 (`--max-running-requests 16 --cuda-graph-max-bs-decode 16`), only with an approved memory plan (A2). Expected 175–185 tok/s aggregate; its value is shorter queue waits, not throughput.
3. After C5: A4 (speculation off at high concurrency) only if B1 shows the per-request cost scales with verified tokens.

One change per restart, measured, kept or rolled back, as in the runbook.

## 7. Questions to ask upstream

1. DeepEP: is EP over an LSA team spanning PCIe P2P peers (no NVLink between some peers) expected to work with `EP_DISABLE_GIN=1`? Is "PCIe kernel support" planned soon?
2. #92: drafter placement (replicated or sharded) and the peak extra memory of load-time repack at EP4.
3. #200: any known issue combining it with #92's SM90 path, or registering about 196 GB of `/dev/shm` inside an unprivileged container?
4. kabishou11 fork: interest in running its H100 layouts on a 4× H100 NVL (94 GB) node and returning JSONL.
