# Portable GPU + LiteLLM + 1M setup

**DeepSeek-V4.1-Flash-1017 is deployed on the existing four GPUs.** The pinned checkpoint preserves 1,048,576 total tokens and DSpark block five. Actual DSH processed 1,007,752 input / 431 output tokens, with the complete correct saved answer in **27m33.97s**. All **60/60** tracked short replies passed alongside it, with a paired median of **5.11s**. The accepted cold run had zero automatic retries, allocator mapping warnings or unexpected model restarts. The corrected 128 MiB temporary score tiles retain the full KV pool; preparation is slower than the rejected 256 MiB trial. [Checkpoint setup and complete results](../docs/MODEL_UPDATE_1017.html).

| Setting | Installed value |
|---|---|
| Checkpoint | DeepSeek-V4.1-Flash-1017, revision `1bae0e1088993b9b82de08f59de5be5a34e42170` |
| Total context / output ceiling / reserve | 1,048,576 / 8,192 / 256 tokens |
| GPUs / speculative decoding | Existing four H100 NVL / DSpark block five |
| Static memory / active cap / decode graph cap | 0.923 / 8 / 8 |
| Prefill chunk / maximum prefill / prefill requests | 1,024 / 1,024 tokens / 2 |
| Prefix tails / decode interval / preparation step | 16 / 4 / 2,048 tokens |
| Full / sliding-window KV slots | 1,150,976 / 17,920 |
| Temporary attention-score tile | 128 MiB |
| Long admission | One input-plus-reserved-output request above 131,072 tokens; one FIFO waiter for at most 1,500 seconds; excess long waiters receive 429 |

| Verified workload | Result |
|---|---|
| Cold near-1M DSH | 1,007,752 input / 431 output; 27m33.97s total; first text 1650.96s; 149.15 streaming output tokens/sec |
| Ordinary work during cold preparation | 60/60 exact, saved, retry-free replies; 3.13–9.22s; paired median 5.11s; two eight-client bursts |
| Cached substantial output | 1,008,209 input / 1,199 output; 15.13s; 159.22 streaming tokens/sec; exact and saved |
| Real file tool continuation | 1,009,686 input; 12.94s; actual printf/write, cat/read and rm/delete command inspected, successful tool result and absent file checked |
| 256K stage | 257,688 input / 7 output; 147.06s; 12 overlapping correct short replies; zero allocator warnings |
| Structured short answers | Three exact, saved 599-token outputs at 163.34–166.48 streaming tokens/sec per conversation |
| Short-client bursts | 31/31 exact persisted replies across 1, 2, 4, 8 and 16 simultaneous native DSH clients; GPU active cap eight, additional clients queue |
| Managed clients | Claude Code ordinary reply 1.17s; TrueForge ordinary reply 0.73s with persisted assistant output verified. These are new-checkpoint ordinary tests, not fresh near-1M CLI acceptance |
| History preservation | All 167 original histories / 188 session files across 20 main runtimes retained their IDs and bytes |
| GPU memory observation | Four H100 NVL devices; minimum observed free memory 38 MiB per GPU in one-second sampling. Temporary headroom remains tight; two full-1M requests are not an accepted case |

## Earlier checkpoint: DSpark configuration and measured behavior

**Earlier checkpoint qualification, 19 October 2026:** actual DSH processed **1,007,752 input / 431 output tokens** with the complete correct saved answer in **22m22.2s**. **46/46 ordinary replies** passed during long preparation (**3.56–11.21s**, paired median **5.08s**), including two eight-client bursts. The qualifying model generation had **zero retries, allocator warnings or unexpected restarts**. Three 599-token structured short answers streamed at **164.60–166.11 tokens/sec per conversation**. Explanatory prose samples measured **76.76–96.76 tokens/sec**. One expensive request is admitted at a time; up to **eight** requests run actively, with additional ordinary clients queued. [Results and setup](../docs/DSH_PLATFORM_GUIDE.html#guide-section-10).

| Setting | Qualified value |
|---|---|
| Total context | 1,048,576 tokens across main DSH, LiteLLM and SGLang |
| Model / GPUs | DeepSeek-V4.1-Flash, tensor parallel 4, existing node |
| Recorded GPU memory | Four H100 NVL devices reporting 95,830 MiB each |
| Speculative decoding | DSpark, block size 5 |
| Static memory | 0.923 |
| Active requests / CUDA graph cap | 8 / 8 |
| Prefill chunk / batch budget | 1,024 / 1,024 tokens; two prefill requests; separate prefill/decode |
| Prefix tails / decode interval | 16 / 4 |
| Full / sliding-window cache slots | 1,150,976 / 17,920 |
| Attention-score temporary tile | 256 MiB |
| Preparation step | 2,048 tokens at the final forwarding boundary |
| Long admission | One active request above 128K; one FIFO waiter, at most 1,500s; further long requests receive 429 |
| Output budget | At most 8,192 tokens plus a 256-token safety reserve |

| Actual DSH check | Measured result |
|---|---|
| Focused 256K stage | 257,691 input; exact seven-token answer in 130.57s; eight correct short replies, median 3.56s |
| Recorded near-1M known-answer task | 1,007,752 input / 431 output; **22m22.2s**; exact and saved |
| Near-1M answer stream | **147.82 tokens/sec** |
| Ordinary replies during long work | **46/46** exact, saved and retry-free; **3.56–11.21s** |
| Ordinary paired median | **5.08s** |
| Eight-client cohorts during long work | Two completed cohorts at prepared prefixes above 600K and 900K |
| Structured short answers | Three outputs of 599 tokens; **164.60–166.11 streaming tokens/sec each** |
| Natural-language samples | First: 406 tokens at 76.76 tokens/sec; factual correction: 350 tokens at **96.76 tokens/sec**, final content reviewed |
| Cached near-1M continuation | 1,008,209 input / 1,199 output; **14.86s**; **158.32 streaming tokens/sec** |
| Actual near-1M tool continuation | 1,009,673 input; **13.42s**; actual file create/read/delete checked |
| Short client bursts after capacity run | **31/31** exact saved replies across 1, 2, 4, 8 and 16 clients; active GPU cap stays eight |
| Full near-1M qualification failures | **0 retries / 0 allocator warnings / 0 unexpected restarts** |
| Existing history preservation | **167 histories / 188 files across 20 runtimes** retained IDs and bytes |

These fresh client bursts ran after the identical-profile handover. The GPU admits at most eight active requests; a 16-client burst queues additional requests.

| Clients | Correct replies | Elapsed per reply | Stream tokens/sec per conversation | Combined tokens/sec over full cohort |
|---:|---:|---|---|---:|
| 1 | 1/1 | 1.29–1.29s | 169.05–169.05 | 92.35 |
| 2 | 2/2 | 2.59–2.84s | 70.96–138.66 | 83.76 |
| 4 | 4/4 | 2.87–3.88s | 54.86–102.88 | 122.43 |
| 8 | 8/8 | 3.20–5.98s | 49.89–99.33 | 158.45 |
| 16 | 16/16 | 3.11–11.21s | 47.91–104.15 | 169.01 |

Combined throughput includes the cohort request window and is not the rate of a single conversation.

[Detailed trials and setup](../docs/PERFORMANCE_OPTIMIZATION_20261018.html). Earlier dated measurements below retain their original profiles.

## Earlier setup and qualification records

## Latest existing-node allocator acceptance

The revised profile passed an actual DSH turn with **1,007,697 input / 119 output tokens**, returning the complete expected answer and persisting it with **zero retries**. Whole-turn time was **1475.94 seconds**; the answer streamed in **3.54 seconds**, approximately **33.34 output tokens/second**. Streaming rate excludes preparation, queueing and agent overhead.

**62/62 overlapping short DSH replies** were complete, exact and persisted, with zero retries, in **5.58–11.69 seconds** (median 7.62). Their measured output streams delivered **21.62–36.42 tokens/second**. The late eight-client cohort started after a recorded **907,264-token** prepared prefix; all eight passed in **7.09–7.63 seconds**, with the actual long turn active before and after.

The final run recorded **zero allocator mapping warnings and zero unexpected model restarts**. The prior mixed-batch candidate failed and is preserved in the [allocator report](../docs/GPU_ALLOCATOR_QUALIFICATION_20261017.html). This profile separates prefill/decode and caps a prefill batch at two requests while retaining parallel ordinary decoding and the 16-running-request cap. It is not sixteen maximum contexts, a fresh-cluster acceptance or an SLA. The earlier fresh-model record below belongs to its own historical profile.

## Existing-node runtime acceptance

An earlier fresh, site-adapted model deployment using the pinned image and its recorded preceding profile passed an actual **1,007,695-input-token DSH turn** and bounded mixed concurrency on 17 October 2026. The existing weight snapshot, gateway/database and a disposable DSH runtime were used. The startup progress deadline is 2,100 seconds; no extra GPU node was used. The test does not qualify a new cluster, download, private storage, or two full-1M sessions. [Results and retained limitations](../docs/FRESH_GPU_ACCEPTANCE_20261017.html).

This is the public counterpart for the GPU inference portion of the deployment repository. It contains sanitized source and a renderer, not a copy of private cluster configuration. No organization endpoints, node names, private registries, credentials, user identities, central-share paths or live workload IDs are required by this bundle. Public upstream image digests and model names remain to identify the qualified software.

## Features and design

```mermaid
flowchart LR
  D[Private DSH runtime] --> L[Authenticated LiteLLM :4000]
  C[Managed Claude Code / TrueForge] --> L
  L --> F[Loopback final-payload guard :4001]
  F --> S[Shared SGLang :8000 / four GPUs]
  L --> P[Private PostgreSQL]
  W[Pre-staged read-only weights] --> S
```

- One shared model copy; user workspace/history isolation belongs to the DSH deployment, not to GPU allocation.
- 1,048,576 total tokens, at most 8,192 output tokens and a 256-token reserve. The final forwarded messages/tools are counted with the backend tokenizer. Input plus requested output plus reserve must fit.
- One request with input plus reserved output above 131,072 is admitted at a time. One additional long request may wait in a bounded FIFO position for up to 1,500 seconds; excess waiting requests receive 429. Early streaming comments keep cancellation available during waiting/preparation. The two configured aliases have no hidden rate-limit retries. Ordinary work remains concurrent; the current model running cap is eight; it is not eight full-1M conversations.
- Small prefill chunks (512; maximum prefill 1,024), separate prefill/decode batches, a two-request prefill cap, a pinned scheduler reservation and a single chunk-owner guard bound transient attention work. Four decode rounds run between prefill batches; ordinary decoding remains parallel up to the shared running cap. Eight additional sliding-window prefix tails allocate capacity for prefix reuse within the same static memory budget. They are not an eight-user limit or a guarantee that every long prefix survives diverse concurrent traffic; an eight-diverse-request test exposed cache loss. Before each long warm step, foreground streams may drain for up to eight seconds. This is cooperative scheduling, not preemption or a latency guarantee.
- One gateway replica with Recreate is essential: admission uses a local process-shared file lock. Do not scale replicas/workers without a distributed admission design.
- Only two local aliases are exposed. There is no external fallback. No ingress, public hostname, shared workspace, database password or client API key is embedded. The final-wire listener binds to loopback and is never a Service.

## Setup method

1. Use a new test namespace first. Install the NVIDIA device plugin and an enforcing Kubernetes network-policy implementation through the cluster's approved process. Reserve four compatible GPUs and sufficient host memory; the template requests 256 GiB RAM and permits 512 GiB. Check node capacity before scheduling. No extra node is assumed.
2. Pre-stage the licensed/approved model files on a PVC named `model-weights`, at `/approved` within the volume. Verify the complete weights against the approved upstream manifest, revision and hashes. `config.json` existence is only a startup check, not integrity evidence. Review any model code before allowing `--trust-remote-code`; the cache is read-only and runtime downloads are disabled. The model image is public and digest-pinned. Registry/image availability and model license approval remain operator prerequisites.
3. Provision PostgreSQL with protected durable storage and recovery according to your environment. In this namespace its pods must have `app: llm-database` and listen on 5432. This bundle does not install or migrate a database. An external database requires a separately reviewed narrow egress rule; do not permit all egress to make startup pass.
4. Create two existing Secrets through your private secret-management process: `local-inference-credentials` with `LITELLM_MASTER_KEY` and a random `INTERNAL_ROUTE_KEY`; `local-inference-database` with `DATABASE_URL`. Never commit their values or rendered secret manifests. The master key is for operators; issue restricted model-only per-runtime virtual keys to clients, not the master key. Check management endpoints are denied for those keys.
5. Install Python 3.10+ and PyYAML for rendering. Copy `settings.example.json` to a private settings file outside the repository. Set the namespace/PVC/Secret names and qualified gateway digest. Run:

   ```sh
   python gpu-stack/render.py --settings /private/settings.json --output /private/candidate.yaml
   kubectl -n <test-namespace> apply --dry-run=server -f /private/candidate.yaml
   ```

   The renderer does not create the namespace or contact the cluster. It rejects unexpected setting keys, invalid names, mutable image tags and overwriting an existing candidate. Review the emitted objects before applying. Pin changes to the SGLang image require requalifying both scheduler source hashes; changed source fails closed.
6. Apply only to the reviewed test namespace. Database/Secrets/PVC must already exist. NetworkPolicy allows same-namespace `inference-client: allowed` pods to reach the authenticated gateway, the gateway to reach only the model/database/DNS, and the model no outbound network. There is no direct client access to the unauthenticated model. Namespace label changes and allowed-client labels are operator privileges. DNS examples assume ordinary kube-dns labels: verify against your CNI and NodeLocal DNS implementation. Generic DNS access is not protection against DNS exfiltration; use an internal-only resolver and test it before classifying the whole environment No Internet. Client, execution-worker and database policies are separate required controls.
7. Verify actual readiness, image IDs, mounted source hashes, model identity, token limits and an authenticated exact reply. Check key-management denial, direct model denial, endpoint-override rejection, public TCP/domain/direct-IP/DNS denial and internal service access. Readiness alone is insufficient. Do not replace a working Production service with this portable candidate without these checks.
8. Point managed DSH/CLI profiles at the private gateway Service with restricted keys. Set matching 1M context, output ceiling, long-response timeout and compaction budget. The existing DSH managed transport handles the qualified SDK's character-based output-budget bug; this GPU bundle does not install those client hooks. Follow [client setup and results](../docs/LLM_SETUP_AND_TEST_RESULTS.html) and qualify each installed client/version separately.

## Qualification, performance and rollback

Run progressive 128K, 256K, 512K and near-1M tests with distributed known answers and source citations, plus substantial output and real tool continuation. Verify persisted replies, exact final payload counts, cancellation, over-budget refusal, second-long admission/429, zero hidden retries and cache reuse with normalized tool defaults. During each long test run real short DSH conversations; record time to first text, elapsed time, output length and output rate separately. A direct API burst is not end-to-end DSH or CLI acceptance.

The 17 October accepted reference used 1,007,697 input / 119 output tokens and completed in **24m36s**, with **33.34 streaming output tokens/sec** and 62 correct overlapping ordinary replies. The 18 October larger-step and DSpark experiments did not qualify an operating improvement: DSpark produced 162.50–165.61 tokens/sec on structured short answers, then failed long-input temporary-memory allocation; 8,192-token preparation steps lost a long prefix after diverse concurrent short traffic. The original model and 2,048-token preparation step were restored. Consult the [optimization report](../docs/PERFORMANCE_OPTIMIZATION_20261018.html) for recovery, measurements and rejected profiles. These results belong to the recorded deployment, rather than fresh tests of this generic template.

`DSH_LONG_WARM_STEP_TOKENS` is an operator-only guard setting, default **2,048**. It accepts multiples of 512 between 512 and 8,192 and rejects invalid values at startup. It controls final-wire preparation calls, independently of the engine's 512-token prefill chunk. Do not increase it based on short-only timing. Numeric progress telemetry records preparation/cached token counts, request time and foreground-yield time without prompt contents or token IDs.

Before changes, save private manifests, exact images, source ConfigMaps, settings and state-preservation checks. Recreate of the only GPU deployment interrupts inference; prepare a maintenance handover. Keep the exact last qualified 1M specification, image and source overlay available, with the earlier 128K guardrail as a separate fallback. Roll back on startup failure, incorrect replies, lost history, regression in ordinary latency or GPU restart. Restore an explicitly saved qualified specification; do not blindly undo to the immediately previous revision, which may be a rejected experiment. Reconcile newer durable writes before any storage restore; changing inference should not change storage mounts. This bundle does not mount or migrate user data.

## Source maintenance and publication boundary

`runtime/` is a reviewed public derivative of the deployment's forwarding/guard/scheduler source. Deliberate differences: the tokenizer URL is mandatory configuration, unrelated-provider fallback is rejected, synthetic prompt capture is removed, and organization-specific patch marker names are neutralized. Algorithm constants and patch-source hashes are retained. Regenerate/review/test these copies when canonical code changes; do not maintain divergent fixes silently. `SOURCE_MANIFEST.json` binds this publication to source-content hashes without disclosing private repository paths or endpoints.

The new bundle is sanitized. Existing repository documentation/history contains site-specific deployment records; this addition does not redact that earlier material or claim repository-wide sanitization. Private settings, keys, database URLs, infrastructure addresses, storage paths and generated cluster output must stay outside Git. Existing Production remains unchanged by rendering or publishing this bundle.

## CI activation

`ci-example.yml` is a reviewed GitHub Actions example, not an active workflow. The publishing token cannot create/update workflow files, so an authorized repository maintainer must copy it to `.github/workflows/portable-gpu.yml` to enable automatic checks. The Linux qualification was run directly; publishing this example does not claim hosted CI passed. It runs the guard/manifest/privacy checks and rejects canonical forwarding-source drift.


## Bounded long admission and cancellation

The final-wire route admits one long request and one FIFO waiter (up to 1,500 seconds); excess long waiters receive an immediate capacity error. Ordinary requests bypass that lock. Streaming clients receive content-free SSE comments during waiting/preparation, so cancellation can propagate before model output. A single inference replica/process is required; this is not a distributed admission queue. The legacy callback default remains 300 seconds. See [actual DSH acceptance](../docs/ADMISSION_RESPONSIVENESS_20261017.html).
