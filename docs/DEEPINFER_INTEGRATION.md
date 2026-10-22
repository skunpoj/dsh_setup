# DeepInfer integration on the existing four GPUs

DeepInfer is the official DeepSeek inference engine. It is a different runtime
from the SGLang service currently used by DSH through LiteLLM. Installing the
Python package or renaming a model alias does not switch that engine.

## Current implementation status

The read-only candidate gate is implemented in
[`scripts/deepinfer_preflight.py`](../scripts/deepinfer_preflight.py). It checks
the exact engine revision, attention/MoE dependency pins, actual kernel-source
bytes and observed GPU compute capabilities. It does not install packages,
allocate a CUDA context, load model weights, or change the service. Even an
architecture pass is explicitly **not Production acceptance**.

The 22 October review checked official revision
`9bd9cf243fc53ef9afbf8f04d391d989117d6ab9`. This is newer than the 21 October
review, but retains FlashMLA `2e5429fc5653bab6e081f09477126f731882a6a9`
and DeepGEMM `1fc9c66975ee322d628b3288534ca0e9ce12a64d`.
FlashMLA's sparse decode and fused attention reject architectures other than
SM100. The inspected Mega-MoE implementation dispatches only to SM100.
Fresh discovery on the existing node reports **four H100 NVL GPUs, SM90**.
Consequently this candidate is blocked before installation; DeepInfer is
**not deployed or benchmarked**. The working SGLang service remains in use.

## Fresh compatibility review - 23 October 2026 (ICT)

The current official main revision remains `9bd9cf243fc53ef9afbf8f04d391d989117d6ab9`.
Read-only checks at 03:09-03:12 ICT confirmed the same dependency pins and
architecture restrictions. FlashMLA sparse decode checks `is_sm100f()`;
Mega-MoE dispatches to the SM100 implementation and otherwise rejects the
architecture. Actual NVML discovery reported four H100 NVL GPUs with compute
capability 9.0. No validated SM90 fallback was found in this candidate.

**Decision: do not install or switch to this DeepInfer release on the existing
four H100s.** No engine build, model reload, inference call, history migration
or storage change was performed for this review. SGLang remains the serving
engine. This is a compatibility failure for the reviewed release, not a claim
that an H100 port is theoretically impossible.

### Actual comparison status

| Required comparison | DeepInfer | SGLang recorded reference |
| --- | --- | --- |
| Existing four-H100 compatibility | Blocked by reviewed kernel paths | Existing serving engine |
| Current matched near-1M answer and compaction | Not run | Latest corrected 22 October candidate stopped at its memory-warning gate; near-1M compaction did not start |
| Concurrent ordinary requests | Not benchmarked | 53 short replies during that partial preparation; median 4.66 s, maximum 11.78 s, zero retries |
| Throughput advantage | No measurement | No matched engine comparison; historical near-1M success is a different profile |

The SGLang numbers are dated recorded samples, not fresh benchmarks or an SLA.
See the [full preparation and rollback review](GPU_PREPARATION_REVIEW_20261022.html).
No DeepInfer speedup, completed comparison, or current full near-1M acceptance
is claimed. A supported H100 implementation must first pass numerical/cache
compatibility and memory checks. Only then should an isolated same-node
handover compare the same checkpoint, tokenizer, complete DSH payload, output
budget and short-request schedule, followed by real compaction, cancellation,
recall and persistence checks. Preserve the working SGLang image/profile and
routes for rollback, without changing history/workspace mounts. This plan uses
the existing node; it does not require or recommend purchasing hardware.

## Reproduce the compatibility check

Run this in a separate checkout and environment. Never run upstream `build.sh`
inside the working SGLang container: it replaces dependencies including NCCL.

```sh
git clone https://github.com/deepseek-ai/DeepInfer.git
git -C DeepInfer checkout 9bd9cf243fc53ef9afbf8f04d391d989117d6ab9
git -C DeepInfer submodule update --init vendor/FlashMLA vendor/DeepGEMM
python scripts/deepinfer_preflight.py --source DeepInfer --output deepinfer-gate.json
```

Exit **78** means the observed hardware fails the reviewed architecture gate.
Exit **0** means only the architecture gate passed. Missing/modified source or
invalid hardware observations cause an error. The receipt is created once;
choose a new filename for a later check. A saved hardware CSV can be supplied
with `--hardware-csv`; retain its actual collection time separately.

## Work needed to implement a real H100 engine

1. Provide H100 implementations for sparse prefill/decode and fused
   normalization/RoPE/attention/cast, preserving V4.1 cache format, scales,
   attention sinks and variable-length behavior. Do not remove architecture
   guards or substitute an older FlashMLA version without format validation.
2. Provide compatible MoE dispatch, weight/scale transforms and scratch-memory
   sizing for this model on the same four GPUs. Generic H100 support elsewhere
   in DeepGEMM does not implement the Mega-MoE functions used here.
3. Build the candidate in a separate immutable image. Validate numerical
   equivalence, cache layout, memory use and small offline inference before
   attempting longer prompts. The official example's roughly 32K configuration
   is not a 1M qualification.
4. Supply the online serving integration: exact chat/tool tokenization, cache
   ownership and eviction, streaming, cancellation, bounded admission and
   timeouts behind LiteLLM. The open-source release supplies offline inference;
   it does not include the complete production cache/service layer.
5. Use a controlled handover on the existing node after those gates pass. Keep
   the accepted SGLang image, configuration and route for rollback. Do not
   change workspace/history mounts for an inference-engine trial.
6. Test actual DSH at short, 128K, 256K, 512K and near-1M inputs with ordinary
   conversations running concurrently. Measure preparation, first text,
   output tokens/sec, memory and short-request latency separately. Also test
   tools, cancellation, compaction/recall and history preservation.

None of these gates can be replaced by the SM100 benchmark figures in the
official README. No DeepInfer speedup on the installed H100s is claimed.

Sources: [pinned official engine](https://github.com/deepseek-ai/DeepInfer/tree/9bd9cf243fc53ef9afbf8f04d391d989117d6ab9),
[FlashMLA architecture guard](https://github.com/deepseek-ai/FlashMLA/blob/2e5429fc5653bab6e081f09477126f731882a6a9/csrc/api/common.h),
[Mega-MoE dispatch](https://github.com/deepseek-ai/DeepGEMM/blob/1fc9c66975ee322d628b3288534ca0e9ce12a64d/csrc/apis/mega_moe.hpp).
