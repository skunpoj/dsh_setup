> Implementation and live-model source revision: GPU_server `12e1d8993e5dff093bb2d6eba301976a7c0b7f13`. The running deployment metadata records that revision; the base image and overlay hashes are detailed below.

> Mirror of the GPU_server experiment record. Response/log files below are bundled in [context-evidence](context-evidence/); model implementation paths belong to GPU_server.

# Interactive scheduling: interference, correction and evidence

Date: 15 October 2026, ICT. Hardware: existing single node, four H100 NVL GPUs.

## What went wrong

The earlier 1M experiments used the shared Production model endpoint. During the user's 15:28–15:33 slow turn, model logs showed a long prefill with approximately 502,296 pending input tokens at 15:28 and another request queued. This establishes shared-service interference during the testing window. It does not map every model request to a particular DSH session or attribute all five minutes of that turn to one cause.

The previous experiment gates tested short-request concurrency after long requests finished. Those gates proved recovery, not interactive responsiveness during a long request. A scheduler ceiling of 16 and a large cache pool did not establish latency isolation. Reducing prefill chunk size solved a memory problem but did not by itself solve admission or decode starvation.

## Reproduced baseline

`scheduling_probe.py` runs a synthetic long request directly against the backend while sending four short streaming requests through the normal LiteLLM route. It emits usage, time to first output token (TTFT), total duration, exact answers and whether each short finishes before the long request. No credentials or full prompts are retained in results. A unique prefix avoids reuse of the previous long synthetic prefix.

The baseline long request used 133,044 input tokens and returned `LONG_SCHEDULE_OK` in 35.573 seconds. Idle short requests completed in approximately 0.32 seconds. The four short requests submitted during prefill took 32.375–33.578 seconds, returned `SHORT_SCHEDULE_OK`, and all completed after the long request. This is a controlled reproduction of head-of-line blocking, recorded in `scheduling-before-20261015.json`.

## Implemented correction

1. A narrow scheduler overlay reserves up to 512 tokens from the existing chunk budget when a small waiting request is detected. Eligibility is based on total input/output history minus the cached prefix known to the scheduler, not just the latest user message. It prioritizes waiting tails of at most 512 tokens and preserves FCFS within each lane. The long request retains at least one page of progress. Allocation, cache ownership, SWA admission, cancellation and token-capacity checks remain the upstream implementation.
2. `--enable-mixed-chunk` permits already-admitted decode work to share a chunked-prefill batch.
3. `--prefill-decode-interval 4` permits decode rounds between prefill batches. It trades some long-prompt throughput for interactive output progress.
4. `--enable-metrics` enables operational measurement. The model remains TP=4, static memory 0.90, chunk size 1,024, max prefill tokens 2,048, maximum running requests 16, context ceiling 1,048,576. DSH/LiteLLM retain the 131,072-token user budget.
5. The Service no longer publishes unready addresses. This avoids advertising a booting model as a usable endpoint; it does not eliminate the single-node reload outage.

The base image is pinned at digest `sha256:4a5d132a06a77c8331e15845f2e925adc788b00105097ad55409afa3f4fa4860`. An init container prepares a read-only scheduler overlay from a tracked ConfigMap. It refuses an original source hash other than `a27879971d17033955847d79b2e6ebc5604da419fe6ffee43c5c107479ffc97e`. The V1 overlay hash was `419f13ccc05a7181f6bf0d3fbcbcd82028afbf066f580c74c35584cf33a69e38`; V2 is `88e1b661a6ef83cc53de519e43ab25ec109f37f622cba3bd98a47dfd3c3c58ef`. Upstream upgrades must review this insertion point and rerun interference tests; blindly accepting a new hash is not safe.

## Acceptance and limits

### V1 measured results and discovered gap

| Test | Long input | Long completion | Short TTFT during long | Short completion during long | All shorts completed before long? |
|---|---:|---:|---:|---:|---|
| Before, original scheduler | 133,044 tokens | 35.573 s | 32.116–33.319 s | 32.375–33.578 s | 0/4 |
| After, same short-prompt pattern | 133,039 tokens | 39.927 s | 0.511–1.032 s | 0.935–1.450 s | 4/4 |
| After, fresh uncached short prompts | 133,045 tokens | 40.291 s | 0.212–0.652 s | 0.581–1.025 s | 4/4 |

The fresh short requests used 239–247 prompt tokens and eight output tokens each. Every short returned `SHORT_SCHEDULE_OK`; every long returned `LONG_SCHEDULE_OK`. The first after-run's long completion increased by approximately 12.2% versus the baseline; this is the measured tradeoff in one synthetic run, not an isolated causal throughput estimate or a production percentile. The repeated after-run also had a function-call probe submitted to the shared service during the same window.

A third V1 test used a warmed shared context of approximately 24K tokens with a new small suffix. All four requests still waited 33.008–34.066 seconds and completed after the 35.830-second long request. This failed the intended continuing-session gate, despite the successful tiny-prompt tests. The failed result is retained in `scheduling-v1-cached-session-failed-20261015.json`.

The DSV4 cache does not advertise fast prefix matching. FCFS therefore left `num_matched_prefix_tokens` unset before the reservation classifier ran; the classifier saw the full 24K input rather than the cached tail. The upstream admission loop found the cached prefix later, after the long chunk had already consumed the budget. V2 calls the upstream prefix matcher once for classification and leaves normal admission refresh/allocation checks intact. The extra private flag records classification only; it does not change KV ownership. A targeted lazy-prefix test was added to the budget/hash checks. V2 required a second model reload, which is recorded rather than treating the V1 probe as complete closure.

The function-call regression through the Secure runtime and LiteLLM returned `finish_reason=tool_calls`, function `lookup_case`, and arguments `{"case_id":"1213"}`. No actual business tool was executed. A log extract records prefill batches containing multiple requests while more than 117K long-input tokens remained pending, corroborating the measured overlap rather than only testing after completion.

The replacement initialized in approximately nine minutes. Post-test readback showed Ready true, zero restarts and the pinned image digest. Initialization warned about unsupported FlashInfer allreduce fusion and missing tuned FP8 kernel configurations; the runtime selected its fallback paths. These warnings are retained as performance-tuning leads, not labelled as OOM failures.

Evidence files: `scheduling-before-20261015.json`, `scheduling-after-20261015.json`, `scheduling-after-cold-20261015.json`, `scheduling-tool-call-20261015.json`, `scheduling-runtime-readback-20261015.json`, and `scheduling-interleaving-20261015.log`. The probe itself is versioned as `scheduling_probe.py`. JSON timestamps are UTC; this report uses ICT. Monotonic times in each file compare events within that run and are not calendar timestamps.

### Final V2 results and deployment decision

| Test | Long input tokens | Long completion | Short TTFT during long | Short completion during long | Finished before long |
|---|---:|---:|---:|---:|---|
| V2 cached continuing sessions | 133,044 | 39.635 s | 0.441–1.045 s | 0.861–1.466 s | 4/4 |
| V2 fresh small requests | 133,040 | 39.185 s | 0.217–0.672 s | 0.588–1.044 s | 4/4 |

The cached-session requests carried 24,059–24,064 total input tokens. The runtime log shows reuse of 23,808 cached tokens in batches with more than 118K long-input tokens still pending. The cold small requests carried 242–246 input tokens. All eight returned `SHORT_SCHEDULE_OK`; both long requests returned `LONG_SCHEDULE_OK`. The final long runs took approximately 10–11% longer than the single 35.573-second baseline. Input counts vary slightly because each run uses a unique nonce; this is a synthetic comparison, not a statistically controlled production benchmark.

V2 also passed the required `lookup_case` function-call regression through Secure and LiteLLM. The active pod was `vllm-deepseek-v4-1-flash-5ddc98546f-m7tcl`, image digest matched the pin, overlay annotation was `interactive-v2`, Ready was true and restart count was zero. This zero count means no unplanned restart of that pod; there were two deliberate model replacements during the overall work. Both required roughly nine minutes to initialize.

The revised profile is retained. Evidence: `scheduling-v2-cached-session-20261015.json`, `scheduling-v2-cold-20261015.json`, `scheduling-v2-tool-call-20261015.json`, `scheduling-runtime-readback-20261015.json` and `scheduling-v2-interleaving-20261015.log`. Five local checks cover source-hash rejection, chunk-budget conservation, long-request progress, disabled/small budgets and lazy cached-prefix classification. The local checks do not replace the live response/ordering gates.

Run `python test-evidence/validate_scheduling_evidence.py test-evidence/scheduling-v2-cached-session-20261015.json test-evidence/scheduling-v2-cold-20261015.json` to read and validate the retained results. To repeat live, copy `scheduling_probe.py` into the Internet runtime and run it with `SCHED_CACHED_SHORT=1` and `SCHED_COLD_SHORT=1` separately, redirecting JSON to new evidence files. This intentionally submits work to the shared model and should be scheduled with awareness of active users. The long leg bypasses the 128K client guardrail only for the authorized backend test; normal short legs use LiteLLM.

The probe initially attempted an unsupported `/tokenize` request shape and received HTTP 400 before starting its long leg. That setup attempt was discarded; the completed probes use actual returned usage counts. No successful result is inferred from that failed setup.

The acceptance target for this bounded probe is: all four exact short answers complete in less than five seconds and before the long response ends; the long answer also completes; no model restart or scheduler/OOM exception occurs. This is a test target, not a production percentile SLA.

The reservation is deliberately limited. Large cold prompts, requests without usable prefix-cache matches, saturated request slots and exhausted cache capacity can still queue. It is not arbitrary-length per-user latency isolation or a substitute for admission control. This patch has not established fair service at near-1M aggregate occupancy or with sustained adversarial short traffic. The former successful million-token test belongs to the previous scheduling profile; a later change must not inherit that result as a fresh validation.

Health-check log rates and post-test subsecond sentinel replies are not sustained user tokens/sec benchmarks. Compare TTFT, streaming gaps, completion time, long-request progress, memory pressure and output correctness during contention rather than quoting one throughput counter.

## Rollback and operational experience

Before applying the change, the model was confirmed idle and deployment/Service snapshots were saved at `C:\Users\skunpojt\rollback-scheduling-20261015`. The only model process must reload for this scheduler change, so the change creates an inference interruption. Readiness protects endpoint publication; it cannot create high availability without another running inference process.

Rollback restores the saved deployment, removes its scheduler overlay/flags and waits for real inference recovery. Retain the ConfigMap until no pod references it. The broader 128K safety rollback and all earlier context experiments remain documented in [context-optimization-20261015.md](CONTEXT_OPTIMIZATION_20261015.md).

Lessons: separate capability tests from responsiveness tests; include a mixed-load gate before promotion; prefer bounded synthetic input over another unrestricted million-token stress run; keep checkpointed rollback; preserve the failed configuration and observed warning instead of treating an HTTP 200 as proof of stability.
