# DeepSeek-V4.1-Flash on 4× H100 NVL: production setup and measured results

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
- **The "1..40" prompt is not a general speed:** counting is so predictable that DSpark accepts most draft tokens. On ordinary text both engines run at 58–68 tok/s for one user.
- **Long context:** DeepInfer has no prefix cache yet. The first token takes 38.6 s at 127K, 145 s at 498K and 301 s at 995K tokens, and a follow-up turn is no faster.

## Files

| Path | Purpose |
| --- | --- |
| [`scripts/v41_h100/stream_bench.py`](../../scripts/v41_h100/stream_bench.py) | Per-user streaming benchmark: TTFT, decode tok/s, aggregate, server queue state |
| [`scripts/v41_h100/run_matrix.sh`](../../scripts/v41_h100/run_matrix.sh) | Workload × concurrency matrix, identical for every engine |
| [`scripts/v41_h100/parse_decode_log.py`](../../scripts/v41_h100/parse_decode_log.py) | Accept length and step time per batch size from SGLang decode logs |
| [`scripts/v41_h100/bucket_trace.py`](../../scripts/v41_h100/bucket_trace.py) | GPU time per kernel bucket from a torch-profiler trace |
| [`scripts/v41_h100/allreduce_lat.py`](../../scripts/v41_h100/allreduce_lat.py) | All-reduce latency at decode-sized messages |
| [`scripts/v41_h100/ckpt_admission.py`](../../scripts/v41_h100/ckpt_admission.py) | Per-GPU weight bytes from safetensors headers (no tensor reads) |
| [`scripts/v41_h100/deepinfer_sm90.sh`](../../scripts/v41_h100/deepinfer_sm90.sh) | DeepInfer #92 + #200 fetch and merge, sm90 build, probes, tests, first offline load |
| [`scripts/v41_h100/perf_model.py`](../../scripts/v41_h100/perf_model.py) | Step-time model for projected tok/s figures |
| [`scripts/v41_h100/sm90_probes.py`](../../scripts/v41_h100/sm90_probes.py) | CUDA P2P matrix, NCCL load/store domain size seen by DeepEP, `/dev/shm` + `cudaHostRegister` probe |
| [`scripts/v41_h100/workloads/`](../../scripts/v41_h100/workloads/) | Synthetic prompts: code, JSON, maths, English and Thai chat |

## References

DeepInfer pull requests and discussions this work builds on or relates to:

- [#47](https://github.com/deepseek-ai/DeepInfer/pull/47) (sicnuyudidi): RFC, SM90 (H20-3E) support.
- [#92](https://github.com/deepseek-ai/DeepInfer/pull/92) (DarkraiHL): SM90 (Hopper) support, V4.1-Flash end to end on 8×/4× H20-3e. The base of our engine.
- [#148](https://github.com/deepseek-ai/DeepInfer/pull/148) (yuyu5333): SM90 kernels for H100/H200/H20, validated on 8× H20.
- [#180](https://github.com/deepseek-ai/DeepInfer/pull/180) and [#235](https://github.com/deepseek-ai/DeepInfer/pull/235) (tonyh168): SM90 platform support for V4.1 on H20, and SM90 sparse MLA on Triton with a reproducible H20 image.
- [#88](https://github.com/deepseek-ai/DeepInfer/pull/88), [#91](https://github.com/deepseek-ai/DeepInfer/pull/91), [#101](https://github.com/deepseek-ai/DeepInfer/pull/101) (JianWang97): SM90 BF16 TFLOPS limits, and the MXFP4 → FP8 expert conversion and loader. FP8 experts double expert memory, which is why we stay on FP4 experts at 94 GB per GPU.
- [#200](https://github.com/deepseek-ai/DeepInfer/pull/200) (JohnQin-llm): opt-in UVA Engram fetch for single-node deployments (tested on B200/B300). Used on this node, which has no RDMA NIC.
- [#99](https://github.com/deepseek-ai/DeepInfer/pull/99): NVLink Engram fetch (one all_to_all per step), the other GIN-free option; #200 measured its decode slower than the default path because its buffers are sized for prefill.
- [#147](https://github.com/deepseek-ai/DeepInfer/pull/147) (kzjeef): minimal OpenAI-compatible server over the offline engine, used for the matched benchmark.
- [#238](https://github.com/deepseek-ai/DeepInfer/discussions/238): question on official H200 (SM90) support.

Libraries and forks:

- [DeepEP](https://github.com/deepseek-ai/DeepEP), [DeepGEMM](https://github.com/deepseek-ai/DeepGEMM), [FlashMLA](https://github.com/deepseek-ai/FlashMLA): DeepEP is not used here (cross-socket P2P drops writes, so experts go over NCCL); DeepGEMM's FP8×FP4 MQA-logits kernels need SM100+, so SGLang's indexer falls back to torch on SM90; [#92](https://github.com/deepseek-ai/DeepInfer/pull/92) builds FlashMLA's SM90 path.
- [humming](https://github.com/vllm-project/humming) ([`humming-kernels` on PyPI](https://pypi.org/project/humming-kernels/)): the W4A8 MoE backend [#92](https://github.com/deepseek-ai/DeepInfer/pull/92) uses on SM90. We pin 0.1.13: LunarFeller reported a misaligned read in 0.1.12 on H200 (comment on #92), fixed upstream in 0.1.13. [kabishou11/deepinfer-hopper](https://github.com/kabishou11/deepinfer-hopper) maintains #92 as a Hopper-first fork with untested H100/H200 layouts and the same pin.

Model and other engines:

- [deepseek-ai/DeepSeek-V4.1-Flash-1017](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017), revision `1bae0e1088993b9b82de08f59de5be5a34e42170`.
- [SGLang cookbook: DeepSeek-V4.1](https://docs.sglang.io/cookbook/autoregressive/DeepSeek/DeepSeek-V4_1): our serving baseline (preview build with DSpark); lists H200, B200, B300, GB300 and MI355X, not H100.
- [SGLang discussion #39791](https://github.com/sgl-project/sglang/discussions/39791): earlier public V4.1-Flash on H100 reports (about 40–50 tok/s single request, OOM at larger prompts or two parallel requests).

Our code, plan and measurements: [skunpoj/dsh_setup → docs/deepseek-v41-h100](https://github.com/skunpoj/dsh_setup/tree/main/docs/deepseek-v41-h100) and [scripts/v41_h100](https://github.com/skunpoj/dsh_setup/tree/main/scripts/v41_h100).
