# GPU serving comparison and administrator change plan

**One current report:** [View the PDF](GPU_PLATFORM_REVIEW.pdf)
([direct download](https://raw.githubusercontent.com/skunpoj/dsh_setup/main/docs/gpu-platform/GPU_PLATFORM_REVIEW.pdf)).

The report starts with contents before the executive summary. The executive summary contains
the concise short-prompt comparison plus two one-million-token experiment tables. Section 1
combines the methods and detailed measured matrix, presents W1/W3/W4 once, separates
measured results from a conditional expected-outcome calculation, and describes
the actual LiteLLM-to-DeepInfer route. The current container uses an SGLang
dependency-base image, while PID 1 executes mounted DeepInfer source with the
NCCL expert-communication backend. Base image, running engine and mounted source
are separate identities and must be verified separately.

![Measured output per GPU versus stream-derived TPOT](throughput-latency.png)

![Matched one-million-token experiment timing](long-context-comparison.png)

The graph uses our finite HTTP-cohort measurements, not PR246's B200 data.
Four allocated GPUs, three repeats, offeredC1/2/4/8/16, active cap8. W3 is a
predictable counting workload; it is not a generic conversational benchmark.

- [SVG graph](throughput-latency.svg)
- [Long-context SVG graph](long-context-comparison.svg)
- [Measured CSV](../../gpu-stack/benchmarks/measured-results.csv)
- [Measured JSON](../../gpu-stack/benchmarks/measured-results.json)
- [Conditional W1 scenario and assumptions](conditional-scenario.json)
- [Matched one-million-token results and limits](matched-1m-results.json)
- [Middle-retrieval and long-output one-million-token results](matched-1m-middle-long-results.json)
- [Original HTTP probe](../../gpu-stack/benchmarks/http_probe.py)
- [Three serving profiles and code inspector](../../gpu-stack/profiles/README.md)
- [Administrator procedure and recovery runbook](../../gpu-stack/runbooks/gpu-peer-access.md)
- [GPU source ownership and release map](../GPU_SOURCE_OWNERSHIP.md)
- [Related engine source fork](https://github.com/skunpoj/DeepInfer/tree/c1b8cc6da34ac17c1f2522baa1ddf98a5a1d49ca)

The report includes two fresh, serial, direct-engine one-million-token checks per
engine. The first checks an exact instruction at the end with a short response;
the second checks a unique value near the middle and requests up to 1,024 output
tokens (981 from SGLang; 1,024 from DeepInfer). They are one-run, single-user synthetic checks, not cache-controlled,
multi-user, statistical or post-change results. The proposed after-host-change profile is **not deployed or
qualified**. A fresh comparison of all 293 mounted Python paths against the
current public DeepInfer successor found 17 byte-identical files, 274
line-ending-only differences, two content differences and no missing path. The
two content differences are newer public fixes not yet in the known-working
runtime. The previously staged offline controls are now committed publicly. The
count-only tokenizer privacy successor remains mounted through the private
operational source. A prior private release verified its own 293-file manifest
and one authenticated, non-sensitive DSH to LiteLLM to DeepInfer request returned
the exact expected text without retry. The retained offline example is not the
running server path. This supersedes the earlier selected 264-match and
289-byte-match wording. Compiled/image provenance, host peer-copy, DeepEP and
post-host-change performance qualification remain open. No host reboot,
`iommu=pt`, ACS/BIOS change, DeepEP activation or benchmark is claimed. Internal endpoints,
identities, secrets and private operational evidence are not published here.
