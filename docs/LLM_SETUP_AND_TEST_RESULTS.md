# Shared LLM — Setup and Verified Test Results

**Live configuration clarification, 16 October:** DSH does not currently have end-to-end 1M access through LiteLLM. Fresh readback found the SGLang backend at 1,048,576 tokens, but LiteLLM’s loaded callback enforces 131,072 total tokens, 8,192 maximum output and a 256-token reserve. The legacy `dsh-secure` runtime still contains `contextWindow: 1048576` in `/state/cordis.patch.yml`; this is a configuration mismatch, not proof of usable 1M requests. The table below describes the intended product budget, not a fresh verification of every runtime profile. No runtime settings were changed in this clarification. Performance figures remain recorded samples, not a new benchmark.

## Results that users can rely on

These are recorded tests, not a new benchmark performed by opening this guide. Rates include queue, prefill and network time; they are not sustained decode throughput or an SLA.

| Test | Observed result | What it establishes |
|---|---|---|
| Short exact replies, 16 October | 0.223–0.233 seconds | Basic internal inference returned the required text |
| Two simultaneous 119-token replies | 3.381–3.385 seconds; 35.16–35.20 effective output tokens/sec each | Two ordinary requests ran concurrently |
| Short replies during fresh 24,044-token input | 0.440–0.588 seconds; larger request completed in 4.956 seconds | All three short replies completed while larger work was still active |
| Near-1M historical backend test | 1,000,015 input + 10 output tokens; exact `LONG_1M_RETEST_OK` | That earlier backend profile completed one near-1M request |
| Current DSH end-to-end 1M / two simultaneous 1M requests | Not established | The backend test does not qualify those product behaviors |

The 16 October measurements are in [the exact response/timing record](context-evidence/performance-private-live-20261016.json). The historical result is [recorded separately](context-evidence/near-1m-response-chunk1024.json). Neither is a substitute for application-level task correctness.

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
| DSH compaction | Configured at 75%, approximately 98,304 tokens; success is session-dependent |
| DSH runtime | `0.2.0-rc.2`, independently verified from the running package |

The source model manifest and live deployment matched this pinned SGLang image during this review. LiteLLM's live spec still uses `main-latest`; record its actual running digest and pin a qualified digest before reproducing or upgrading it. A mutable tag alone is not a reproducible installation. The actual resolved LiteLLM image at this review was `ghcr.io/berriai/litellm@sha256:4870893763aca143f590bd5685a25219037af027d1d27e97abcb17ac9ec5d09f`; retain that recorded digest as the installed baseline and qualify it before any upgrade. [Readback record](context-evidence/llm-setup-readback-20261016.json).

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

Keep DSH upstream updates separate from SGLang/model/scheduler upgrades. The prepared upstream workflow checks npm channels and tests a candidate before proposing a package-pin PR. GitHub publication is currently blocked by missing workflow permission on the stored PAT; it is not active. It does not merge or deploy Production. Qualify copied-state migration, browser/WebSocket behavior, compaction, private-user/network boundaries and restart/restore before release.

On regression, restore the saved compatible Deployment/configuration pair and repeat exact inference plus DSH access/persistence tests. Do not replace newer workspace/history data with an older snapshot merely to roll back an image. The [maintenance procedure](UPSTREAM_SYNC_AND_INTERNET_POLICY.md) and [existing context trial record](CONTEXT_OPTIMIZATION_20261015.md) remain separate technical references.
