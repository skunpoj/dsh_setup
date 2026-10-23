# GPU, LiteLLM and local inference setup

<!-- GPU_PERFORMANCE_STATUS_20261023:START -->
## GPU performance and 1M operation — 23 October 2026

- **100+ output tokens/sec is not yet qualified for the latest near-1M optimization.** The last completed cold actual-DSH prose run used 1,008,049 input / 540 output tokens: **28m32.25s preparation**, **66.00 wire-streaming tokens/sec**, zero retries.
- Latest completed full-model candidate M: **74.03 tokens/sec at 128K** and **75.85 at 384K**; its near-1M stage was rejected after one allocation retry on each GPU. No substantial near-1M output or new compaction result was obtained.
- **136/136 ordinary replies** passed recorded content checks with zero retries. The **86 replies during near-1M preparation** had **4.28s median / 6.48s p95 / 9.40s maximum** native turn time.
- N9 passed five bounded BF16 numerical cases with zero allocation retries/OOMs, using synthetic metadata and no model weights. Full-model near-1M throughput for that fix is not yet qualified.
- The restored 18:16 ICT snapshot is **SGLang on four H100s**, not DeepInfer: memory fraction **0.922**, **1,024 / 1,024-token prefill**, **1,048,576 context tokens**, eight active requests and one above-128K input admission lane; shorter work remains parallel. The older 158.04 tokens/sec numeric-short median and 117.75 combined four-client rate are different measures.
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
