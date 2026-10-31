# DeepInfer evaluation on the existing four H100 GPUs

**21 October 2026 — rejected at the hardware-compatibility gate.** The current official release is not a drop-in executable candidate for this deployment. No DeepInfer speedup has been measured here. The working SGLang route, 1M budget, storage mounts and histories were not changed by this evaluation.

## Decision and actual checks

We pinned DeepInfer to `774ce244b87cc0eb8d4b94ab9f5de2ab22049f01`, inspected its checked-out dependencies and ran its NVIDIA discovery code through NVML without creating a CUDA context. All four installed H100 NVL devices reported compute capability **9.0 (SM90)**.

| Check | Observed result | Consequence |
|---|---|---|
| Official engine support | The pinned README lists NVIDIA SM100 | H100 is outside the advertised engine support |
| Pinned FlashMLA | Revision `2e5429fc5653bab6e081f09477126f731882a6a9` explicitly removed Hopper support; sparse decode and fused attention require `is_sm100f()` | The current attention dependency cannot simply replace our H100 path |
| Actual architecture predicate | `is_sm100f()` returns `major == 10`; source-predicate controls reject 9, accept 10, reject 11 | Our observed major 9 fails this necessary gate; this is a source-level test, not a GPU kernel benchmark |
| Pinned DeepGEMM | Revision `1fc9c66975ee322d628b3288534ca0e9ce12a64d` has some generic SM90 kernels, but the Mega-MoE dispatch inspected here only selects architecture major 10 | A library advertising H100 support does not establish compatibility of every function used by DeepInfer |
| Build procedure | Installs a different CUDA/PyTorch dependency stack and force-reinstalls NCCL | It must not be run inside the accepted model container |
| Online serving scope | The release does not include the complete production KV-cache service and load-balancing layer | A successful offline example would still not qualify DSH admission, streaming, cancellation or persistence |

No model weights were loaded, no additional GPU allocation was requested, no packages were installed in Production, and no serving process was restarted for this audit. Kernel guards were inspected rather than bypassed. Consequently, there is **no new DeepInfer near-1M, concurrency or compaction benchmark**. A future Hopper port is not ruled out; the conclusion applies to these pinned sources.

## Which delay could its ideas address?

The latest accepted native DSH test remains **1,008,049 input / 540 output tokens**: **28m32.25s** preparation, **28m46.85s** total, and **66.00 streaming output tokens/sec** after preparation. During that run, numeric and prose short-turn medians were **4.04s / 6.05s**, with zero retries. These are prior recorded SGLang results, not DeepInfer measurements.

The corresponding retained-history test started from **948,102 input tokens**. Its automatic summary took **393.12s**, followed by **388.90s** for the rebuilt-context response. All **23** concurrent numeric replies were exact and retry-free; median **6.04s**, maximum **10.06s**. The two stages must be measured separately.

DeepInfer documents a decoder-side bounded replay that rebuilds a short sliding-window suffix instead of executing all decoder prefill rows. The encoder still processes the relevant input. This is model execution, not a shortened DSH transcript. Its Q&A describes approximate sliding-window reconstruction, so adopting it also requires quality and tool-use validation; the published prefill benefit cannot be extrapolated to our H100 timings.

DSH compaction instead writes a summary and constructs a different active prompt. Saving the complete conversation does not save GPU KV state, and a changed prompt prefix can require substantial preparation again. A faster inference kernel might help either stage, but bounded decoder replay does not by itself reuse a summary prompt's KV state for a differently ordered final prompt. This is an architectural inference, not a new cache experiment.

## Practical plan on the same node

Keep the qualified H100 SGLang service while testing compatible ideas independently. The promising areas are fewer redundant final-payload preparation calls, stable exact-token prefix reuse, H100-compatible attention implementations, and scheduling that bounds long prefill work. Environment variables intended for DeepInfer do not enable those algorithms in SGLang.

Before an engine candidate is allowed onto these GPUs, it must demonstrate the complete required attention/MoE/cache path on SM90, compatible weights and cache layouts, and bounded scratch memory. Merely checking out the older Hopper-capable FlashMLA commit is insufficient: the upstream dependency changed model support and KV formats as well as hardware support.

Qualification then proceeds through small correctness and memory tests, progressively longer inputs, and actual DSH near-1M preparation and automatic compaction. Run short DSH requests concurrently; record first text, completion time, streaming rate, retries and maximum gaps separately. Check tools, Stop/resume, preserved event prefixes, summary/reference recall and file hashes across process replacement. An offline throughput number is not acceptance of the complete online route.

No second model can be assumed to fit beside the current four-GPU instance. Any later full-engine test on the same allocated GPUs needs an explicitly coordinated maintenance handover. Preserve the exact accepted deployment specification, immutable image and source ConfigMaps; keep the old route and durable storage intact. Restore the saved specification on startup, capacity, correctness, memory or short-latency regression. Restore current durable writes before any historical storage recovery; an inference rollback should not roll back conversation files.

## Reproduction and references

The sanitized compatibility receipt records pins, source hashes, predicate controls and test scope. The probes used source inspection and NVML discovery only; they provide no claim of zero overhead for an untested engine. Another chat's separately coordinated optimization experiments are outside this assessment.

- [Pinned official DeepInfer README](https://github.com/deepseek-ai/DeepInfer/blob/774ce244b87cc0eb8d4b94ab9f5de2ab22049f01/README.md)
- [Pinned official deployment Q&A](https://github.com/deepseek-ai/DeepInfer/blob/774ce244b87cc0eb8d4b94ab9f5de2ab22049f01/doc/inference_deployment_qa.md)
- [Pinned FlashMLA support notice](https://github.com/deepseek-ai/FlashMLA/blob/2e5429fc5653bab6e081f09477126f731882a6a9/README.md)
- [Pinned FlashMLA architecture predicate](https://github.com/deepseek-ai/FlashMLA/blob/2e5429fc5653bab6e081f09477126f731882a6a9/csrc/api/common.h)
- [Pinned sparse-decode guard](https://github.com/deepseek-ai/FlashMLA/blob/2e5429fc5653bab6e081f09477126f731882a6a9/csrc/api/sparse_decode.cpp)
- [Pinned Mega-MoE dispatch](https://github.com/deepseek-ai/DeepGEMM/blob/1fc9c66975ee322d628b3288534ca0e9ce12a64d/csrc/apis/mega_moe.hpp)
- Accepted DSH setup and measured results
