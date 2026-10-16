# Shared LLM — Setup and Verified Test Results

**Extensive live review, 16 October:** DSH does not currently have end-to-end 1M access through LiteLLM. The SGLang backend is configured for 1,048,576 tokens. All 20 main runtime web-profile files declare 131,072 context and 8,192 output for the DeepSeek aliases. Boot-free composition of the legacy owner's and private admin's web profiles confirms those values. The legacy home-level 1M entry refers to an older GLM configuration; it does not establish a 1M DeepSeek web route. The mounted LiteLLM callback uses 131,072/8,192/256, with coverage limitations detailed below. No model, gateway or DSH server was restarted or reconfigured during this investigation.

**Correction:** automatic compaction is not simply 75% of 128K. The installed plugin subtracts output reservation and headroom too. Its normal calculated threshold is **57,344 estimated tokens**, not 98,304. This is a code/configuration calculation, not a fresh successful compaction of a real historical session.

## Results that users can rely on

These are recorded tests, not a new benchmark performed by opening this guide. Rates include queue, prefill and network time; they are not sustained decode throughput or an SLA.

| Test | Observed result | What it establishes |
|---|---|---|
| Short exact replies, 16 October | 0.223–0.233 seconds | Basic internal inference returned the required text |
| Two simultaneous 119-token replies | 3.381–3.385 seconds; 35.16–35.20 effective output tokens/sec each | Two ordinary requests ran concurrently |
| Short replies during fresh 24,044-token input | 0.440–0.588 seconds; larger request completed in 4.956 seconds | All three short replies completed while larger work was still active |
| Near-1M historical backend test | 1,000,015 input + 10 output tokens; exact `LONG_1M_RETEST_OK` | That earlier backend profile completed one near-1M request |
| Current DSH end-to-end 1M / two simultaneous 1M requests | Not established | The backend test does not qualify those product behaviors |
| Fresh review: two simultaneous replies | 3.377–3.381 seconds; 35.19–35.24 effective output tokens/sec each | Both returned the exact requested 1–40 sequence |
| Fresh review: short replies during 24,048-token input | 0.446–0.591 seconds; larger request 4.948 seconds | Three exact short answers finished before the larger answer |

The earlier 16 October measurements are in [the exact response/timing record](context-evidence/performance-private-live-20261016.json); the fresh review is in [the new response/timing record](context-evidence/llm-review-performance-20261016.json). Fresh isolated short replies took 0.230–0.246 seconds. The historical million-token result is [recorded separately](context-evidence/near-1m-response-chunk1024.json). None is a substitute for application-level task correctness.

## Live stress retest — 16 October 2026

**Passed: 105/105 synthetic responses across 18 stages**, from 19:37:31 to 19:41:27 ICT. The test used the real internal LiteLLM streaming route from Secure, its existing inference credential, temperature zero and fresh nonce prefixes. It changed no settings, created no DSH histories and read no business data. This is an inference-route test, not a DSH browser/agent or compaction test.

### Concurrent bursts

Each concurrency level ran three times. Every response had to contain the requested complete 1–40 sequence after whitespace normalization. Actual completion counts varied from 80 to 119 tokens because formatting varied; rates use returned token usage rather than an assumed 119 tokens. TTFT means time to first streamed content or reasoning event. Percentiles are nearest-rank values from these small samples, not service-level guarantees.

| Concurrent requests | Responses verified | TTFT p95, seconds | Completion p95, seconds | Effective output tokens/sec per request | Aggregate output tokens/sec across rounds |
|---|---|---|---|---|---|
| 1 | 3/3 | 0.131 | 3.694 | 32.1–32.3 | 32.1–32.3 |
| 2 | 6/6 | 0.320 | 3.700 | 32.2–34.5 | 53.8–66.1 |
| 4 | 12/12 | 0.356 | 3.827 | 29.8–32.4 | 105.3–124.3 |
| 8 | 24/24 | 0.856 | 5.145 | 21.5–26.8 | 168.0–179.9 |
| 16 | 48/48 | 1.966 | 7.460 | 13.1–18.6 | 214.5–229.4 |

More concurrency increased aggregate throughput while each request became slower. Sixteen is a tested burst level for these short outputs, not a promise of sixteen large contexts or sustained-load capacity. Rates include queue, prefill and network time; they are not isolated steady-state decode speed.

### Short replies during larger uncached input

One larger synthetic request ran alongside three sequential short probes. Returned usage verified each input size; all nine short probes returned the expected sentinel before their larger request completed.

| Actual larger input tokens | Larger completion, seconds | Short completion range, seconds | Short TTFT range, seconds | Shorts finished before larger response |
|---|---|---|---|---|
| 24,043 | 5.223 | 0.476–0.486 | 0.159–0.169 | 3/3 |
| 96,046 | 26.041 | 0.475–0.495 | 0.155–0.178 | 3/3 |
| 120,048 | 35.528 | 0.475–0.545 | 0.157–0.229 | 3/3 |

The sampler observed **16 running requests and a queue peak of 12**. Queueing is therefore not absent, despite the responsive short mixed-load probes. Forty-four GPU/queue samples completed without monitor errors. Minimum sampled free GPU memory was 4,592–4,594 MiB per GPU; sampled GPU utilization reached 100%. These samples do not establish the exact transient memory peak.

The model pod identity and zero restart count stayed unchanged. The test interval contained no matches for the checked CUDA OOM, OutOfMemoryError, illegal-memory-access or scheduler-exception signatures. A separate post-test request returned exactly `STRESS_HEALTH_OK` in **0.256 seconds**. Running model/LiteLLM imageIDs and start times were read back; both retained zero restarts, with the existing model arguments.

### Stop conditions, reproduction and limits

The probe requires idle admission metrics before each stage. It stops escalation on inference errors, incorrect output, changed model pod/image/restart state, burst completion over 15 seconds, larger completion over 40 seconds, or short mixed replies over five seconds or without observed overlap. Completed/stopped stages are saved rather than overwritten. An independent readback validated all response content, finish reasons, returned token counts and model error-signature counts.

```powershell
python scripts/stress_live_inference.py --output stress-new-run.json
```

This deliberately loads the shared service; run it when idle. It is a bounded burst/mixed-load stress test, not a destructive OOM or prolonged saturation exercise. It did **not** test arbitrary tool schemas, images, complete DSH tasks, compaction, current near-1M operation or two concurrent 1M requests. The backend remains configured for 1,048,576; testing stayed within the existing 131,072-token LiteLLM budget. No limit was raised for this run.

Evidence: [complete request/sampling record](context-evidence/inference-stress-20261016-live.json), [independently recalculated tables and executed probe hash](context-evidence/inference-stress-summary-20261016.json), [post-test sentinel, imageIDs and arguments](context-evidence/inference-stress-postcheck-20261016.json). Raw logs are linked supporting material, not embedded in the main risk narrative.

## Current service layout and limits

`Private DSH runtime → internal LiteLLM :4000 → SGLang :8000 → shared four-H100 model`

The Kubernetes deployment is named `vllm-deepseek-v4-1-flash` for compatibility, but its process runs **SGLang**. The Service remains `vllm-deepseek-v4-flash`.

| Layer | Configuration |
|---|---|
| Model | DeepSeek-V4.1-Flash, tensor parallelism 4 |
| SGLang image | `lmsysorg/sglang@sha256:4a5d132a06a77c8331e15845f2e925adc788b00105097ad55409afa3f4fa4860` |
| Model snapshot | `dba1be0a40aa45a94ad051997016db3960a90277` |
| Backend context ceiling | 1,048,576 total tokens |
| GPU static memory fraction | 0.90 |
| Running-request ceiling | 16; not a guarantee of 16 maximum-length requests |
| Chunk / maximum prefill | 1,024 / 2,048 tokens |
| Scheduling | V2 overlay; mixed prefill/decode; decode interval 4 |
| DSH / LiteLLM user budget | 131,072 total; output ceiling 8,192; proxy reserve 256 |
| DSH compaction | Auto enabled; ratio 0.75, default headroom 65,536; normal calculated pressure threshold 57,344 estimated tokens with 8,192 reserved output |
| DSH runtime | `0.2.0-rc.2`, independently verified from the running package |

The source model manifest and live deployment matched this pinned SGLang image during this review. LiteLLM's live spec still uses `main-latest`; record its actual running digest and pin a qualified digest before reproducing or upgrading it. A mutable tag alone is not a reproducible installation. The actual resolved LiteLLM image at this review was `ghcr.io/berriai/litellm@sha256:4870893763aca143f590bd5685a25219037af027d1d27e97abcb17ac9ec5d09f`; retain that recorded digest as the installed baseline and qualify it before any upgrade. [Readback record](context-evidence/llm-setup-readback-20261016.json).

## Investigation findings and remaining work

The [sanitized live investigation record](context-evidence/llm-extensive-review-20261016.json) includes all 20 main runtime profile reads, two composed web profiles, installed compaction-code hashes, isolated callback cases, live scheduler hash and actual imageIDs. DSH2/DSH3 were not included in this main-runtime profile qualification.

### Compaction policy and configuration precedence

DSH layers bundle defaults, the web profile, the home patch and command-line overlays. Finding a value in one file is therefore insufficient. The supported boot-free configuration dump was inspected for the owner and admin profiles; the launcher rewrites its existing empty profile root but starts no server or session. Both composed DeepSeek routes remain 131,072/8,192. The other 18 main runtime web-profile files match the same configuration hash, but their complete compositions were not individually dumped.

The installed `resolveCompactSpec` function was extracted and executed without creating or changing a session. Its formula is:

```text
threshold = floor(min(context × thresholdRatio,
                      context − reserved output − headroom))
normal case = min(131072 × 0.75, 131072 − 8192 − 65536)
            = 57344 estimated tokens
```

With a 4,096 output reservation the threshold becomes 61,440. A session's explicit request reservation can change it. Default retained-tail ratio is 0.16 and the summarizer's configured-default output allowance is 65,536, which is larger than the gateway's 8,192 ceiling. Clamping can therefore shorten the requested summary budget; this investigation did not establish summary failure or successful compaction of every stored session. Automatic pressure checks occur between agent steps. Oversized single tool results or attachments can still require pruning or overflow recovery. A manual `/compact` may have no useful compactable range and is not a guaranteed repair.

### Gateway guard coverage

The mounted callback is referenced by the live configuration and its isolated ordinary-message case clamps 65,536 requested output tokens to 8,192. Its numeric constants match the repository. Its text does not match: the live overflow message incorrectly says **“1M context budget”**, while the repository says **“verified 128K”**. This is real source/live drift, not a changed numeric capacity.

The installed callback was loaded into a separate Python process inside the gateway image. Synthetic cases confirmed:

| Case | Observed callback behavior | Consequence and evidence limit |
|---|---|---|
| Ordinary Chat Completions messages | Counts messages and clamps `max_tokens` | Demonstrates this callback path, not an exact backend-token guarantee |
| Messages plus function/tool definitions | Counter receives `messages` and `model` only | Tool-schema tokens are omitted from this preflight calculation |
| Responses-shaped `input` / `max_output_tokens` | Returns unchanged without counting | This callback alone does not constrain that shape; live endpoint normalization/availability was not bypass-tested |
| `max_completion_tokens` supplied | Adds clamped `max_tokens` but leaves the other field | Precedence/rejection by later LiteLLM/provider processing still needs route-specific testing |
| Token counter raises | Code falls back to characters/3 plus message overhead | An estimate, not a conservative bound for arbitrary Thai, structured, image or tool content |

The installed counter successfully handled small Latin, Thai and JSON samples, but it was not compared with the backend's exact tokenizer across representative requests. Do not describe the 256-token reserve as proof that all tokenizer or omitted-payload differences fit inside it. The callback also does not scope its numeric ceiling by requested model; other aliases can have smaller advertised windows. This review establishes code coverage gaps, **not a demonstrated exploit or a successful oversized request through the live API**.

### Scheduler, performance and evidence scope

The running model source contains the V2 reservation marker; its SHA-256 is recorded alongside the pinned image. The overlay prioritizes uncached tails of at most 512 tokens while preserving long-prefill progress. Concurrency 16 is an admission ceiling, not a promise of 16 near-1M sessions or a per-user latency guarantee. Long cold inputs, unavailable prefix reuse, full active slots and cache pressure can still queue.

The fresh bounded test verified actual streaming output and overlap during 24K work. Retained V2 tests separately cover approximately 133K backend work with fresh small prompts and cached continuing sessions; see [the scheduling experiment and failures](SCHEDULING_FAIRNESS_20261015.md). The historical near-1M success belongs to an earlier scheduler profile. Neither it nor the fresh 24K test qualifies current V2 near-1M fairness, two concurrent 1M requests, or end-to-end DSH 1M. Model and gateway pods still showed zero restarts at the configuration readback; that is supporting availability evidence, not test correctness by itself.

### Installation safety and next changes

The legacy Azure `litellm/06-litellm.yaml` still contains an explicit master-key placeholder and mutable `main-latest` image. It must not overwrite a live Secret. Read the intended internal routing and existing Secret references, prepare a separate reviewed candidate, pin a qualified image digest, and compare persisted configuration before applying it. A server dry-run cannot prove that placeholder credentials are valid or that a callback import works at runtime.

Prioritize a tested model-specific request envelope that includes tools and supported multimodal inputs, rejects unsupported shapes explicitly, normalizes output-limit aliases and fails closed when reliable counting is unavailable. Align DSH request, summary and compaction budgets with that envelope, then verify real manual/automatic compaction on disposable sessions. Preserve the current scheduler and 128K product budget until a controlled current-profile near-1M acceptance test covers tools, streaming, compaction, memory, concurrent short requests and recovery. This review made no such rollout and did not run another disruptive million-token stress test.

## 1 Prepare the platform

Use the authoritative Azure `GPU_server` repository. Relevant paths are under `deployment/vllm/`:

| Component | Source |
|---|---|
| Model Deployment/Service and startup/readiness probes | `04-vllm-deepseek-v4-1-flash.yaml` |
| Scheduling overlay and expected source hash | `scheduler_fairness_patch.py`, `scheduler-fairness-configmap.yaml` |
| Existing gateway/database templates | `litellm/06-litellm.yaml`, `litellm/postgres.yaml` |
| Current 128K callback/config reference | `dsh-environments/scripts/litellm_custom_callbacks.py`, `dsh-environments/k8s/litellm-config.yaml` |
| Pinned DSH image and private-runtime routing | `dsh-environments/Dockerfile`, `dsh-environments/k8s/` |

Prerequisites: namespace `llm`, the existing four-GPU node and working device plugin, model weights on PVC `model-cache-2tb`, registry access, internal DNS, and approved server/database Secrets. The model weights are mounted at `/models`; verify `config.json` at the pinned snapshot before launch. Model loading is offline after staging the approved weights.

```powershell
kubectl -n llm get pvc model-cache-2tb
kubectl get node dagpu-gn-p1
kubectl -n llm get secret litellm-secret litellm-db-secret
```

Inspect Secret names/existence only; do not export values into logs or Git. Existing DSH runtime credentials must remain inference-only virtual keys, not the LiteLLM master key.

## 2 Save a rollback baseline and review the candidate

Save the current Deployment/Service specifications and imageIDs, plus coherent application-state recovery copies under the established procedure. Deployment specs contain Secret references; treat operational exports as private records. Record the scheduler ConfigMap and model digest together so rollback restores a compatible pair.

```powershell
kubectl -n llm get deployment vllm-deepseek-v4-1-flash -o json > model-before.json
kubectl -n llm get deployment litellm -o json > gateway-before.json
kubectl -n llm get pods -l app=vllm-deepseek-v4-1-flash -o jsonpath='{.items[*].status.containerStatuses[*].imageID}'
kubectl -n llm get pods -l app=litellm -o jsonpath='{.items[*].status.containerStatuses[*].imageID}'
```

The model uses all four GPUs and a Recreate strategy. Replacing it interrupts inference on this single-node installation; schedule/drain the work before applying a model change. A startup probe prevents early traffic but does not provide a second model replica.

## 3 Install the matching scheduler and model

From the `GPU_server` checkout, review and server-validate the candidate pair:

```powershell
kubectl apply --dry-run=server -f deployment/vllm/scheduler-fairness-configmap.yaml
kubectl apply --dry-run=server -f deployment/vllm/04-vllm-deepseek-v4-1-flash.yaml
```

During the controlled deployment, apply the reviewed scheduler ConfigMap and then the model manifest. Wait for startup/readiness, inspect initialization logs and read back the actual imageID and arguments. The scheduler patch refuses an unexpected upstream source hash; do not remove that check to force a new image to start. Readiness is followed by actual inference tests below.

## 4 Configure LiteLLM and client limits

Preserve the existing internal model aliases and database configuration. Set the DeepSeek aliases to the internal Service on port 8000, keep external fallback disabled and align the 128K metadata with `DynamicContextClamper`: total 131,072, output 8,192, reserve 256. Mount the callback alongside the configuration and ensure its import path resolves inside the gateway image.

The older `litellm/06-litellm.yaml` contains a placeholder Secret and mutable image tag. **Do not apply that entire file over an existing deployment.** Prepare a reviewed Deployment/Service using the qualified image digest, existing Secret references, database connection and callback mount; validate it before cutover. This guide is an installation order and reference for this existing platform, not a claim that the legacy template is a complete current installer.

Create per-user inference credentials through the established operator path. For example, from `dsh-environments`:

```powershell
python scripts/provision_inference_client.py --secret dsh-inference-example --evidence client-provision.json
```

This operation creates a restricted client credential in Kubernetes; the evidence contains metadata, not the key. Assign it only to its intended runtime. Confirm inference succeeds and management/key/model-creation APIs are denied.

## 5 Connect DSH and validate behavior

Build the pinned DSH package into the runtime image. Keep startup independent of public package installation. Route private users to internal LiteLLM with their own restricted credentials, retain the 128K catalog/compaction settings, and preserve workspace/history mounts during replacement.

Run the bounded synthetic inference test from `dsh-environments`:

```powershell
python scripts/measure_live_responsiveness.py --output llm-acceptance.json
```

Inspect the actual returned strings, token usage, timings and whether short replies finished before longer work ended. Also test a real tool invocation, streaming, login, history, terminal and persistence through the affected DSH UI. Do not infer those behaviors from a direct model response. Near-1M tests require a separate controlled acceptance plan; they are not routine health checks.

## 6 Upgrade and recover without losing boundaries

Keep DSH upstream updates separate from SGLang/model/scheduler upgrades. The expanded upstream workflow checks npm channels, refuses changed patch targets and tests the actual installed candidate and a disposable web server before proposing a package-pin PR. It also tests routing, identity headers, the admin browser dashboard and rollback/manifests fixtures. See the [publication and hosted-run status](UPSTREAM_SYNC_AND_INTERNET_POLICY.md); local tests alone do not establish an active schedule. It does not merge or deploy Production. Qualify copied-state migration, full browser/WebSocket/tool behavior, real compaction, private-user/network boundaries and restart/restore before release.

The workflow is now active and [its first hosted run passed](https://github.com/skunpoj/dsh_setup/actions/runs/38900841456). Downloaded evidence confirmed the candidate image build, ten matching patch targets, actual web startup/authentication/catalog checks, 35 Linux Python cases and admin browser checks. That workflow makes no model call: the measured LLM inference results earlier in this guide remain separate recorded experiments. There was no version change, so no update PR or Production release occurred.

On regression, restore the saved compatible Deployment/configuration pair and repeat exact inference plus DSH access/persistence tests. Do not replace newer workspace/history data with an older snapshot merely to roll back an image. The [maintenance procedure](UPSTREAM_SYNC_AND_INTERNET_POLICY.md) and [existing context trial record](CONTEXT_OPTIMIZATION_20261015.md) remain separate technical references.
