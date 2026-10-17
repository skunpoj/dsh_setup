# GPU allocator warnings and concurrent 1M qualification

## Latest qualification

The revised profile passed an actual DSH turn with **1,007,697 input / 119 output tokens**, returning the complete expected answer and persisting it with **zero retries**. Whole-turn time was **1475.94 seconds**; the answer streamed in **3.54 seconds**, approximately **33.34 output tokens/second**. Streaming rate excludes preparation, queueing and agent overhead.

**62/62 overlapping short DSH replies** were complete, exact and persisted, with zero retries, in **5.58–11.69 seconds** (median 7.62). Their measured output streams delivered **21.62–36.42 tokens/second**. The late eight-client cohort started after a recorded **907,264-token** prepared prefix; all eight passed in **7.09–7.63 seconds**, with the actual long turn active before and after.

| Acceptance check | Recorded result |
|---|---|
| Actual near1M DSH input / complete output | 1,007,697 / 119 tokens; exact known answer and saved prompt |
| Whole long turn / output stream | 1475.94s / 3.54s |
| Long output stream rate | 33.34 tokens/s; excludes preparation and waiting |
| Overlapping short replies | 62/62 exact and persisted; zero retries; 5.58–11.69s |
| Late eight-client burst | 8/8 exact; 7.09–7.63s; long turn active before/after |
| Allocator mapping warnings / unexpected restarts | 0 / 0 in the final model generation |
| Periodic GPU memory sampling | 48 snapshots; minimum observed free 932 MiB; not an allocation-peak guarantee |

The complete model generation log includes startup and the test, with zero allocator mapping warnings, zero scheduler exceptions and no unexpected model restart. Actual image digest, original model runner, source hashes, service target, existing-node placement, four-GPU allocation and server limits were read back after inference. A failed preceding mixed-batch test caused one unexpected restart; it is recorded below and is not erased by the final passing generation.

The same code passed 37 canonical Linux tests and 45 portable Linux tests without skips. These are overlapping canonical/portable suites, not 82 independent behaviors. Readiness and unit tests alone were not used to establish GPU acceptance.

[Sanitized measurements and actual profile](context-evidence/gpu-allocator-qualification-20261017.json). This is a bounded synthetic capacity/concurrency acceptance using a new long-prompt nonce on existing weights and services; it does not establish universal analytical accuracy, a latency SLA or two simultaneous full-million contexts.


## Finding and selected approach

The preceding near1M run returned a correct answer but logged native expandable-segment memory-mapping OOM warnings. A subsequent driver readback showed approximately 10 MiB free per GPU. These messages described allocation retries; the successful turn and zero process-restart count did not make the warnings harmless or establish adequate working headroom.

The warning itself was concrete: the allocator tried to map 20 MiB with only approximately 18–20 MiB free. The investigation kept the existing node and four GPUs. It did not suppress warning output, reduce the context budget, change model weights or disable ordinary concurrency.

An initial experiment added a pressure guard before model forwards. When free memory was below 2 GiB and at least 256 MiB of PyTorch cache was unused, it released unused cache outside CUDA graph capture, at most once per second per worker. Actual numeric events confirmed memory release. Nevertheless, warnings recurred during the second trial. Releasing cached memory before a forward does not reserve sufficient space for peak allocations inside that forward. The experiment therefore failed the warning-free acceptance gate and was removed; it is not included in the default portable deployment.

The replacement uses the original model runner and reduces **prefill chunk size from 1,024 to 512** and **maximum prefill tokens from 2,048 to 1,024**. It also **separates prefill and decode batches** and limits a prefill batch to **two requests**. Smaller token chunks alone proved insufficient: the pinned sparse-attention implementation builds a rectangular temporary gather using the longest sequence and the number of requests in the batch. Mixing many short decoding requests with a near1M prefill expanded that workspace to 7.95 GiB, exceeding the recorded 4.11 GiB free even after cache reclamation.

These limits do not reduce the maximum conversation length: the server still accepts **1,048,576 total context tokens**, with memory fraction **0.90**, four-way tensor parallelism and a **16-request** scheduler cap. Multiple short requests can decode together; four decode rounds are scheduled between prefill batches. A two-request prefill cap is not a two-user or two-running-request limit. The existing gateway admits one request above 128K at a time, permits one bounded FIFO waiter for up to 1,500 seconds, and leaves ordinary requests concurrent. Output remains capped at 8,192 with a 256-token proxy reserve.

The focused concurrency diagnostic also identified loss of a prepared prefix: after an eight-client burst, the backend reported only 6,656 cached tokens against 75,776 previously prepared tokens. The warm loop uses the same token-ID prefix, so this is a cache-reuse failure, not a changed user prompt. The pinned runtime states that prefix reuse depends on retaining the last sliding-window tokens. The preceding profile explicitly set `--swa-prefix-tails 0`, reserving no additional cached-prefix tails.

The replacement therefore also reserves **eight cached-prefix tails** within the existing static budget. Source-based sizing estimates an additional 3,072 sliding-window slots (approximately 68.44 MiB), offset by approximately 44K full-context slots. Startup readback matched the estimate: **1,150,208 full-context slots and 16,640 sliding-window slots**. The startup gate requires at least 1,114,112 full-context slots for this bounded workload. This is a small rebalance of the same memory budget, not additional GPU hardware. The reserve counts cached tails, not users; the running-request cap remains 16. Configuration readback establishes the allocation, while the tests below determine operational acceptance.

| Cache allocation | Earlier smaller-prefill profile | Tail-reserve profile |
|---|---:|---:|
| Total context limit | 1,048,576 | 1,048,576 |
| Full-context token slots | 1,194,240 | 1,150,208 |
| Sliding-window token slots | 13,568 | 16,640 |
| Additional cached-prefix tails | 0 | 8 |
| Static memory fraction | 0.90 | 0.90 |
| Running-request cap | 16 | 16 |

The gateway still extends a prepared prefix by 2,048 tokens per operation. The model divides that work into smaller GPU chunks; the 512-token chunk and 1,024-token prefill cap are different limits from the gateway extension and the 1M conversation budget.

The incremental preparation transport deadline is 30 seconds; the bounded cold-cache probe remains two seconds. Extending the earlier 15-second deadline did not prevent the focused cache loss and is not claimed as its fix. Prompt-free diagnostics now distinguish a failed warm step from an unexpectedly missing cached prefix. Large cache loss still stops preparation rather than falling back to an unbounded monolithic prefill.

More batches can add preparation overhead. No speedup percentage or universal latency guarantee is inferred from the configuration. The actual measurements below distinguish whole-turn latency from streaming output rate.

## Preserved failed experiments

| Trial | Actual result | Disposition |
|---|---|---|
| Cache guard, first cold DSH run | Long preparation stopped, retried twice and was cancelled without its expected answer. 30/30 ordinary replies were exact and persisted, with zero retries, in 5.05–14.12 seconds. Eight concurrent replies took 9.11–9.63 seconds. 84 positive reclamation events; no mapping warning or unexpected model restart. | Failed long-turn qualification. Retained as a failure, not a capacity pass. |
| Same cache guard, fresh cold retest | The mapping warning recurred three times around the recorded 727K prefix. The long turn was cancelled without an answer; it had no retry before cancellation. 44/44 ordinary replies were exact and persisted with zero retries. The model retained its identity and zero restart count. | Failed warning-free acceptance. Guard removed before the smaller-prefill rollout. |
| Smaller prefill, original runner, old preparation deadline | Long preparation retried once and was cancelled without an answer. 30/30 ordinary replies passed with zero retries; the eight-client burst took 10.13–11.67 seconds. No allocator mapping warning or model restart was recorded before cancellation. | Failed full-turn qualification; a warning-free partial run is not 1M acceptance. |
| Focused 256K mixed test, diagnostic gateway | Ten ordinary replies passed, but the long preparation retried after the recorded 75,776 → 6,656 cached-token drop. It was cancelled without its answer. No allocator mapping warning or model restart was recorded. | Established the focused cache-loss event; the earlier generic failures are not retrospectively assigned an unverified cause. |
| Eight cached tails, smaller prefill, mixed decode still enabled | Focused 257,697-input-token run passed with 14/14 ordinary replies. The full near1M run later failed around the recorded 920K prefix during a late eight-client burst: eight mapping warnings and fatal 7.95 GiB sparse-attention workspace allocation, one unexpected container restart, no long answer. Only 2/8 late replies were complete. | Failed full qualification. This exposed the batch-width multiplier and led to separate prefill/decode with a two-request prefill cap. |


The first trial reached a recorded cached prefix of 735,232 tokens before preparation stopped. Additional foreground traffic was present, but the gateway returned only a generic preparation error. Its exact underlying cause was not established. Neither the traffic nor the cache guard is declared the cause. During the second trial the generation-wide reclamation counter reached 1,678 events, including the first trial's 84; this is explicitly a cumulative count, not a separately scoped second-run measurement.

All 84 first-trial events increased measured free memory, by approximately 4.95–5.56 GiB per event. That proves real cache reclamation, not successful near1M completion or elimination of peak allocation pressure. Historical successful 1M tests belong to their recorded profiles and do not retroactively qualify either failed experiment.

The investigation also checked CUDA graph sizing. The installed runner clamps capture batches to its request pool, and the recorded decode graph pool was approximately 0.602 GiB. The metadata ceiling did not establish a 512-request live workload. No graph-size change was made. Unrelated upstream kernel-tuning and deprecation notices are separate from the memory-mapping warning and are not claimed fixed.

The failed mixed-batch controller initially counted zero mapping warnings because it read the replacement container's startup log after the crash. Independent retrieval of the previous container's complete generation log established eight warnings and the fatal workspace allocation. The raw controller record is preserved, with a separate correction receipt; its zero count is not used as a successful acceptance result. This is also why periodic NVML samples are not a guarantee of peak allocation headroom: the lowest sampled free value in that run was 1,608 MiB, while the actual mapping failures occurred with single-digit MiB free.

## Rollout, rollback and reproduction

Before each planned model replacement, current agent activity and long-admission ownership were checked. The exact preceding specifications and immutable scheduler source were retained. A planned model-process replacement is distinct from an unexpected restart during inference. This GPU change does not migrate user storage or replace DSH user runtimes.

The smaller-prefill rollout restores the unmodified model-runner source SHA-256 `de61e79872ecd0ad935b7517a64cefaa7e996520ddec525de42400165c92f9ae` from the pinned image. The existing scheduler overlays remain fail-closed on source drift. Startup/readback failure restores the saved preceding capacity-qualified profile only if this task's candidate is still active; a concurrent change is never blindly overwritten. The preceding profile retained known allocator warnings and is not described as warning-free. Do not blindly undo to the immediately previous revision: earlier revisions include the rejected cache guard and failed mixed-batch profile. Use the explicitly saved capacity-qualified specification, and recheck real inference after restoring it.

The saved original rollback specification passed a fresh server-side dry-run. That validates API admission of the saved specification; it is not an executed rollback or a new inference acceptance of the fallback. The fallback retains known allocator warnings.

For reproduction, use [the portable setup](../gpu-stack/README.md) and `gpu-stack/render.py` with privately supplied weights, credentials, database and site settings. The model template and structural tests pin the smaller prefill budget while preserving context and concurrency. No credentials or private cluster exports are embedded. The publication manifest records source and file hashes. On a single model node, initialization temporarily interrupts inference; qualify a candidate and retain exact rollback before switching a shared service.

The acceptance uses a nonce-prefixed synthetic near1M DSH conversation with a complete known 119-token answer, persisted request/response checks, repeated short conversations and an eight-client burst. It checks capacity, allocator behavior and bounded responsiveness. It is not a new analytical-quality review, sixteen maximum-length requests, two full-million requests concurrently, or an SLA. Failed raw records and experimental source remain preserved privately; the published measurement record contains only sanitized results.

References: [PyTorch CUDA memory management](https://docs.pytorch.org/docs/stable/notes/cuda.html#cuda-memory-management) and [SGLang performance tuning](https://github.com/sgl-project/sglang/blob/main/docs/docs/advanced_features/hyperparameter_tuning.mdx). Runtime conclusions are tied to the pinned image, actual mounted source and recorded tests rather than inferred from current upstream documentation.
