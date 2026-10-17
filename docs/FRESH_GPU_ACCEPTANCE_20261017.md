# Fresh GPU deployment and 1M acceptance — 17 October 2026

**Passed:** a newly started GPU model process served the actual DSH near-1M test, ordinary concurrent requests and a write/read tool continuation. Rollback specifications were retained. This is bounded acceptance, not an SLA.

## What was deployed and what was reused

Fresh GPU model process on the existing four-GPU node using a rendered portable manifest and existing cached weights. Existing LiteLLM/database/auth remained; DSH used disposable state and the deployed managed runtime image/overlays. Not a new-cluster or new-storage installation. The old model process was replaced; user histories, workspaces and credentials were not migrated or changed. The existing weight download was reused; no extra node or GPU was added.

## Measured DSH behavior

| Stage | Input tokens | Output tokens | Elapsed seconds | Verified outcome | Retries |
|---|---:|---:|---:|---|---:|
| DSH-128000 | 135,692 | 8 | 46.13 | Complete persisted reply; input persisted unchanged | 0 |
| DSH-256000 | 263,694 | 8 | 114.21 | Complete persisted reply; input persisted unchanged | 0 |
| DSH-1000000 | 1,007,695 | 8 | 1,247.90 | Complete persisted reply; input persisted unchanged | 0 |
| tool-continuation | 1,008,085 | 8 | 58.30 | Complete persisted reply; tool file written/read and removed | 5 |
| stable-short-tool-retest | 8,080 | 8 | 16.07 | Complete persisted reply; tool file written/read and removed | 0 |
| isolated-estimated-budget-test | 51,431 | 9 | 16.20 | Complete persisted reply; input persisted unchanged | 0 |

## Actual DSH sessions during near-1M work

| Sample | Full reply seconds | First text seconds | Effective output tok/sec | Approximate stream tok/sec | Retries | Verified |
|---|---:|---:|---:|---:|---:|---|
| 1 | 6.61 | 2.92 | 18.01 | 34.70 | 0 | Expected persisted number sequence; long work still active |
| 2 | 6.61 | 3.12 | 18.01 | 35.29 | 0 | Expected persisted number sequence; long work still active |
| 3 | 7.08 | 1.78 | 16.82 | 23.11 | 0 | Expected persisted number sequence; long work still active |
| 4 | 7.09 | 1.84 | 16.79 | 23.11 | 0 | Expected persisted number sequence; long work still active |
| 5 | 7.14 | 3.70 | 16.66 | 36.55 | 0 | Expected persisted number sequence; long work still active |
| 6 | 7.14 | 3.70 | 16.66 | 36.55 | 0 | Expected persisted number sequence; long work still active |

Each DSH sample generated 119 output tokens. Approximate stream rate is (reported output tokens minus one) divided by the first-to-last text-event interval. It excludes first-token delay and is derived from application stream timestamps, not an isolated GPU kernel benchmark. Number-sequence checks ignore whitespace; the near-1M marker uses the complete expected text.

## Concurrency and output throughput

| Case | Requests | Exact | p50 seconds | p95 seconds | Maximum seconds | Effective output tokens/sec per request |
|---|---:|---:|---:|---:|---:|---|
| All bounded ordinary calls | 80 | 80 | 5.23 | 9.93 | 10.08 | 11.31–34.05 |
| Ordinary calls while near-1M work remained active | 48 | 48 | 5.23 | 6.80 | 7.46 | 14.22–33.49 |

| Burst | Concurrency | Aggregate effective output tokens/sec | Maximum reply seconds |
|---|---:|---:|---:|
| baseline-two | 2 | 61.32 | 3.88 |
| during-1m-1 | 2 | 35.37 | 5.62 |
| during-1m-2 | 2 | 42.39 | 4.69 |
| during-1m-eight-2 | 8 | 170.99 | 5.56 |
| during-1m-3 | 2 | 53.20 | 4.47 |
| during-1m-4 | 2 | 51.87 | 3.08 |
| during-1m-5 | 2 | 55.79 | 3.57 |
| during-1m-eight-5 | 8 | 153.22 | 5.44 |
| during-1m-6 | 2 | 44.02 | 5.41 |
| during-1m-7 | 2 | 38.73 | 6.14 |
| during-1m-8 | 2 | 59.53 | 4.00 |
| during-1m-9 | 2 | 53.21 | 3.74 |
| during-1m-10 | 2 | 42.29 | 5.63 |
| during-1m-11 | 2 | 53.30 | 3.73 |
| during-1m-12 | 2 | 44.97 | 3.56 |
| during-1m-13 | 2 | 29.42 | 6.76 |
| during-1m-14 | 2 | 31.90 | 7.46 |
| during-1m-15 | 2 | 29.24 | 6.80 |
| during-1m-16 | 2 | 38.26 | 5.20 |
| after-2 | 2 | 65.30 | 3.64 |
| after-4 | 4 | 103.75 | 3.83 |
| after-8 | 8 | 150.24 | 5.03 |
| after-16 | 16 | 181.01 | 10.08 |

Effective output tokens/sec is reported completion-token usage divided by the entire HTTP request duration, including tokenization, queueing and first-token delay. Aggregate rate divides total completion tokens by the burst wall time. These are not isolated steady-state GPU decode rates. Cold near-1M preparation takes much longer than ordinary replies; a cached continuation is a different workload.

## Follow-up interruption and retained trials

The cold near-1M answer completed without retries. A separate gateway rollout occurred during the first tool continuation: it eventually succeeded after 5 transport/timeout retries. That trial remains recorded rather than being relabelled retry-free. A retained-history fork then began substantial prefix preparation again and was cancelled; no cached-fork latency acceptance is claimed. A fresh short-context write/read test against the stable gateway passed with zero retries. It establishes current tool operation, not retry-free near-1M continuation. The GPU process did not restart. The before/during concurrency samples and later after-bursts are kept separate because the gateway source changed between those phases.

A retained-context padding experiment was cancelled when projected context pressure rose from 1,008,085 to 1,608,135 estimated tokens; it is not a passed capacity result. The isolated high-character budget test uses a fresh synthetic session instead, checks the actual backend-token count and requires a complete multi-token answer. This separates SDK output-budget behavior from retained-history pressure and avoids silently treating a cancelled trial as success. Maintenance coordination must cover complete agent turns and tool continuations, not just the gap between individual long HTTP requests.

## Live profile and rollback

1,048,576 total tokens; 8,192 output ceiling; 256-token reserve; static memory 0.90; running cap 16; prefill chunk 1,024; maximum prefill 2,048; decode interval four. The final-wire guard admits one long request at a time while ordinary calls remain parallel. Sixteen running slots do not establish sixteen maximum-length sessions.

Model image: `lmsysorg/sglang@sha256:4a5d132a06a77c8331e15845f2e925adc788b00105097ad55409afa3f4fa4860`. Running identity/image/restart state remained unchanged through the test sequence. Source and pre-change deployment snapshots were retained privately, with startup-failure and test-failure rollback. No secrets, private endpoints, node names, account names or raw prompts are included in this published summary.

## Limits and lessons

The test validates a fresh model startup and this bounded mixed workload. It does not establish two full-1M sessions, sustained service capacity, a new model download or an entirely fresh cluster/database/storage installation. Small prefill chunks and cooperative foreground scheduling trade long-preparation speed for ordinary-request opportunities. Preserve exact final-envelope token counting and the qualified SDK output-budget patch; a capacity-sized input with a truncated answer is not successful acceptance. Startup took about ten minutes including native kernel compilation. The Deployment progress deadline was raised from 600 to 2,100 seconds to leave headroom above the startup-probe budget; that field change did not restart the model. An independent rollback monitor avoids waiting for a blocked long HTTP test before reacting to a model restart or failed bounded latency/output gate.

[Sanitized measurements](context-evidence/fresh-gpu-acceptance-summary-20261017.json) · [Main setup and historical tests](LLM_SETUP_AND_TEST_RESULTS.html)
