# GPU serving comparison and administrator change plan

**One current report:** [View the PDF](GPU_PLATFORM_REVIEW.pdf)
([direct download](https://raw.githubusercontent.com/skunpoj/dsh_setup/main/docs/gpu-platform/GPU_PLATFORM_REVIEW.pdf)).

The report starts with contents before the executive summary; section 1 explains
the short-cohort and matched one-million-token methods. It presents W1/W3/W4 once, separates
measured results from a conditional expected-outcome calculation, and describes
the actual LiteLLM-to-DeepInfer route. DeepInfer is **not** the vLLM serving engine;
the retained Service name and humming's project ownership do not change that.

![Measured output per GPU versus stream-derived TPOT](throughput-latency.png)

The graph uses our finite HTTP-cohort measurements, not PR246's B200 data.
Four allocated GPUs, three repeats, offeredC1/2/4/8/16, active cap8. W3 is a
predictable counting workload; it is not a generic conversational benchmark.

- [SVG graph](throughput-latency.svg)
- [Measured CSV](../../gpu-stack/benchmarks/measured-results.csv)
- [Measured JSON](../../gpu-stack/benchmarks/measured-results.json)
- [Conditional Test 1 scenario and assumptions](conditional-scenario.json)
- [Matched one-million-token results and limits](matched-1m-results.json)
- [Original HTTP probe](../../gpu-stack/benchmarks/http_probe.py)
- [Three serving profiles and code inspector](../../gpu-stack/profiles/README.md)
- [Administrator procedure and recovery runbook](../../gpu-stack/runbooks/gpu-peer-access.md)
- [Related engine source fork](https://github.com/skunpoj/DeepInfer/tree/b4df8657412de7ea8bab8b442c2b8c68f5c1068a)

The report includes one fresh, serial, direct-engine one-million-token check per
engine using the same prompt hash, request settings and exact-response condition.
That check is not a middle-context retrieval test, multi-user benchmark or
post-change result. The proposed after-host-change profile is **not deployed or
qualified**. Exact engine/binary provenance still has a known tokenizer
difference. No host change or complete authenticated application-path acceptance
is claimed. Internal endpoints, identities, secrets and private operational
evidence are not published in this directory.
