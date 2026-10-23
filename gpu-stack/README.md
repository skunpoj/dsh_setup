# GPU, LiteLLM and local inference setup

<!-- GPU_PERFORMANCE_STATUS_20261023:START -->
## GPU performance and 1M operation - 24 October 2026

- **S compaction-only attempt and recovery, 24 October:** the total-token guard rejected the first attempt before automatic compaction or long model inference. **No 1M capacity test was repeated.** Two ordinary replies completed in **4.05s / 4.07s**, but compaction responsiveness is not established by those cases. All four recovery steps passed: original model/profile restored, temporary test key removed, **32-worker / 256 selected-file** inventories matched; separate fixture **379 sessions / 758 files** preserved. The baseline remains **1M / DSpark / running cap 8**, and its GPU reservation is released. The corrected compaction-only follow-up uses saved history; no completed runtime result is claimed for it.

- **Actual DSH retry R completed:** **1,002,051 input / 636 output tokens**, **29m26.56s preparation**, **29m32.09s to first text**, **29m44.28s whole client turn**, **61.56 streaming output tokens/sec**, zero request retries. All **110 short replies** passed their content checks; **104 completed entirely during the long turn**. Client median/p95/maximum: **6.03s / 10.06s / 14.06s**. The startup fix passed all four bounded startup requests. **100+ per near-1M conversation is not reached.** Strict source-only narrative failed; GPU counter coverage ends five seconds before completion. Forwarding preparation and native time to first text are measured separately. The saved original model specification and a real READY response were verified after recovery; 32-worker / 256 session-and-attachment-file snapshots matched. The experimental profile was not permanently adopted; R did not run compaction.

- **100+ output tokens/sec is not yet qualified for the latest near-1M optimization.** The earlier 21 October cold actual-DSH prose run used 1,008,049 input / 540 output tokens: **28m32.25s preparation**, **66.00 wire-streaming tokens/sec**, zero retries.
- **Final N did not qualify:** 1,002,056 input tokens were tokenized, but only partial prefill ran. Correct numeric/prose short replies took **13.70s / 15.83s native** (**14.11s / 16.06s client**), zero retries. Prose exceeded the unchanged **15s client ceiling**, so the owned long request was stopped. No completed near-1M answer, new long-answer tokens/sec or compaction result. Four-rank zero allocator/OOM deltas cover only the captured partial window. The original source/image/spec and native READY route were restored; recorded 32-worker / 256 session-and-attachment-file snapshots matched.
- Earlier completed full-model candidate M: **74.03 tokens/sec at 128K** and **75.85 at 384K**; its near-1M stage was rejected after one allocation retry on each GPU. No substantial near-1M output or new compaction result was obtained.
- **Trial M: 136/136 ordinary replies** passed recorded content checks with zero retries. The **86 replies during near-1M preparation** had **4.28s median / 6.48s p95 / 9.40s maximum** native turn time.
- N9 passed five bounded BF16 numerical cases with zero allocation retries/OOMs, using synthetic metadata and no model weights. Full-model near-1M throughput for that fix is not yet qualified.
- The restored 18:16 ICT snapshot is **SGLang on four H100s**, not DeepInfer: memory fraction **0.922**, **1,024 / 1,024-token prefill**, **1,048,576 context tokens**, a running-request cap of eight and one above-128K input admission lane; shorter work remains parallel. The older 158.04 tokens/sec numeric-short median and 117.75 combined four-client rate are different measures.
- Earlier 21 October compaction from **948,102 source tokens** passed with **393.12s summary / 388.90s continuation**, **23 short replies** (6.04s median / 10.06s maximum), 0.024s cancellation and preserved recall/history after replacement. That is a dated profile, not acceptance of the latest candidate.

[Full results and definitions](../docs/GPU_TRIAL_STATUS_20261023.html). Generation speed excludes cold preparation; these workloads and timing methods are not a matched before/after benchmark.
<!-- GPU_PERFORMANCE_STATUS_20261023:END -->


Start with the [complete Kubernetes installation](../docs/INSTALL.md). It covers
the runtime image, local configuration, storage, model-weight download, GPU
deployment, internal LiteLLM, private environments, DNS/TLS and verification.
Use [config.example.yaml](../config.example.yaml) for portable settings and the
[templates](../templates) directory for the rendered workload definitions.

Read [1M context operation](../docs/CONTEXT_1M.md) before testing long requests,
then follow the [validation](../docs/VALIDATION.md) and
[acceptance](../docs/ACCEPTANCE.md) checks. Validate the actual hardware, runtime,
memory headroom and concurrent workload; a configured context ceiling is not a
performance guarantee.

For automatic private-workspace provisioning, integrate the
[signup pressure gate](../docs/SIGNUP_CAPACITY.md) with your trusted collector.

This stable guide link points to the current sanitized installation reference.
Supply site-specific endpoints, storage, credentials and certificates privately;
do not publish an operational deployment export or private history here.
