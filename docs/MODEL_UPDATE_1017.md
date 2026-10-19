# DeepSeek-V4.1-Flash-1017 update

The [17 October release](https://api-docs.deepseek.com/news/news261017/) is a new checkpoint, not an automatic update to our existing local weights. The local deployment must download and validate the weights, load them and repeat the affected tests. The existing public model aliases remain stable for DSH, Claude Code and TrueForge.

## Verified rollout, 19 October 2026

**DeepSeek-V4.1-Flash-1017 is deployed on the existing four GPUs.** The pinned checkpoint preserves 1,048,576 total tokens and DSpark block five. Actual DSH processed 1,007,752 input / 431 output tokens, with the complete correct saved answer in **27m33.97s**. All **60/60** tracked short replies passed alongside it, with a paired median of **5.11s**. The accepted cold run had zero automatic retries, allocator mapping warnings or unexpected model restarts. The corrected 128 MiB temporary score tiles retain the full KV pool; preparation is slower than the rejected 256 MiB trial.

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

### Native DSH client concurrency

The cold synthetic task retrieved three known random values from widely separated positions in the input and returned the complete integer sequence 1–200. The cached continuation returned 1–400. These used the real DSH transport and saved response records; they establish the recorded retrieval/output cases, rather than a general repository-analysis benchmark.

| Clients | Correct | Elapsed per reply | Streaming tokens/sec per conversation | Aggregate tokens/sec over cohort |
|---:|---:|---|---|---:|
| 1 | 1/1 | 1.29–1.29s | 163.66–163.66 | 92.02 |
| 2 | 2/2 | 1.82–1.82s | 112.92–124.34 | 130.45 |
| 4 | 4/4 | 2.61–3.12s | 67.24–99.66 | 152.34 |
| 8 | 8/8 | 3.18–5.96s | 49.35–100.00 | 158.43 |
| 16 | 16/16 | 2.89–10.97s | 47.93–104.52 | 172.52 |

Streaming rate measures output after first text. Aggregate rate includes the full cohort window; these are different measures. The 16-client burst queues work above the eight-active GPU cap.

### Cache behavior after load

The immediate near-1M continuation and real tool turn reused prepared context successfully. A later optional operating-note request, after the short-client bursts, re-entered cold preparation and was intentionally cancelled before a generated prose answer. Its cache-miss cause was not isolated. That attempt is retained separately and is not prose-quality acceptance. Stored conversation history remains available independently of GPU KV-cache reuse; the 15.13-second hot result is not a guarantee for every later turn.

## Installed checkpoint

- Repository: `deepseek-ai/DeepSeek-V4.1-Flash-1017`.
- Revision: `1bae0e1088993b9b82de08f59de5be5a34e42170`.
- Download size from the repository manifest: 510,311,045,295 bytes.
- Architecture, configuration, tokenizer and tokenizer configuration match the installed earlier checkpoint. Both configurations declare a 1,048,576-token context and DSpark block size five.
- The reference encoder changes tool-result handling and multimodal ordering. The reference inference implementation also changes. Matching configuration alone does not establish correct execution.
- DeepSeek recommends Harness v0.2.1-rc.1 or later. A Harness package upgrade is a separate compatibility change; downloading weights does not upgrade the application.

The [candidate metadata](../gpu-stack/checkpoints/deepseek-v4.1-flash-1017.json) records the immutable revision and configuration/tokenizer hashes.

## Staging and rollback

The old checkpoint remains available. Download the candidate into a separate snapshot directory and ensure there is space for both versions plus working headroom. Do not delete the old checkpoint to make the candidate fit. The current model cache was expanded online before staging; the model process and user volumes were left in place.

Save the exact live Deployment specification, image identity, runtime patch identities, source hashes and model path before changing the workload. Pin the checkpoint revision rather than downloading a moving `main`. Validate repository file sizes, shard coverage from the weight index and checkpoint contents before selecting it.

Before the handover, check active user agents, model work and the long-request admission lease. Change only the selected checkpoint while retaining the qualified DSpark, prefill, memory, concurrency and admission settings. The single-node handover requires inference initialization. Workspace, history, authentication and network-policy configuration do not need to change.

If the model fails to initialize or the functional checks fail, restore the saved Deployment specification and verify inference through DSH. A disconnected operator channel alone is not evidence of model failure: inspect the actual workload and saved native session before deciding to roll back.

## Operator setup sequence

1. Save the live model Deployment, immutable image identity, runtime overlays and current profile privately. Record current model load and user agents before scheduling the single-node handover. Keep the old checkpoint and exact qualified Deployment available.
2. Stage the public checkpoint in a separate directory through the approved download environment. For an environment with the approved `huggingface_hub` client installed:

   ```python
   from huggingface_hub import snapshot_download
   snapshot_download(
       repo_id="deepseek-ai/DeepSeek-V4.1-Flash-1017",
       revision="1bae0e1088993b9b82de08f59de5be5a34e42170",
       local_dir="/private/staging/deepseek-flash-1017",
   )
   ```

3. Verify the pinned manifest, all expected sizes, every LFS SHA-256, shard coverage from `model.safetensors.index.json`, and the configuration/tokenizer hashes in the [checkpoint metadata](../gpu-stack/checkpoints/deepseek-v4.1-flash-1017.json). A successful download or a readable `config.json` is not this integrity check. Keep the verified snapshot read-only during inference; do not enable runtime Internet downloads.
4. Follow the [portable GPU setup](../gpu-stack/README.md) to render and server-dry-run the candidate. The portable mount exposes approved weights at `/models/approved`; supply the verified snapshot through the site's private PVC configuration. Preserve the stable served model aliases and managed LiteLLM/client endpoints.
5. Inspect the proposed difference, confirm idle admission and user work, then perform the controlled handover. On this one-node installation, loading the weights interrupts inference while initializing. It does not require replacing any DSH workspace, history, account or network-policy mount.
6. Read back the selected snapshot, running image and actual installed module hashes. Require the startup GPU calculation gates, actual short/tool requests and progressive long-context tests below. Check persisted answers and source data/history preservation independently.
7. Publish the checkpoint-specific test results and mirror the reviewed configuration/documentation. If the candidate fails its acceptance criteria, preserve its records and restore the exact qualified profile rather than retrying progressively riskier settings without measurements.

## Acceptance checks

1. Read back the running checkpoint path, immutable image, runtime source hashes, 1M context and DSpark settings.
2. Verify ordinary DSH answers, persisted content, streaming, tool calls and follow-up turns.
3. Verify 1, 2, 4, 8 and 16 concurrent short clients, recording queue time separately from output speed. The active GPU request cap remains eight.
4. Progress through 256K and near-1M input with known answers distributed through the material. Keep short requests running alongside long work. Check retries, allocation warnings and restarts.
5. Verify cached continuation and an actual controlled file create/read/delete tool operation. Confirm user history and workspace preservation independently.
6. Publish checkpoint-specific measurements. Earlier checkpoint timing and token-rate measurements remain historical results and must not be relabelled as results for this candidate.

## Download, compatibility and first live trial

All 83 repository files were size-checked. All 48 weight shards and 49 LFS objects passed SHA-256 verification against the pinned manifest. The old snapshot was retained. All 55 official reference-encoding tests passed after supplying the complete official fixtures and using UTF-8. The configuration, tokenizer and tokenizer configuration are byte-identical to the earlier checkpoint; 96,085 tensor names match. The installed encoder was also compared with representative official prompts, including tools. The local effort default remains unchanged; a matching explicit effort was used for the reference comparison.

The first handover changed only the checkpoint path. The new model loaded on the existing four GPUs and passed the GPU mathematical-equivalence gates, three structured DSH replies and the 256K DSH test. The affected actual DSH results were:

| First 1017 trial | Observed result |
|---|---|
| Structured short answers | Three exact, saved 599-token answers; 164.87–166.57 streaming output tokens/sec |
| 256K input | 257,689 input / 7 output tokens; exact saved answer in 132.94 seconds; 10 correct overlapping short replies |
| Near-1M input | 1,007,752 input / 431 output tokens; complete exact saved answer in 1,351.41 seconds; 147.11 streaming output tokens/sec |
| Ordinary work during near-1M preparation | 52/52 exact, saved, retry-free replies; paired median 4.09 seconds, including two eight-client bursts |
| Stability gate | Eight recoverable allocation warnings, zero fatal signatures and zero unexpected restarts; **not accepted** by the zero-warning qualification rule |

The warning requested a 20 MiB mapping with approximately 17.75 MiB free. Correct output and recovery do not satisfy the memory-headroom criterion. The failed trial remains recorded; it is not relabelled as a fully qualified upgrade.

## Temporary-memory correction

The accepted profile halves the indexer's temporary score-tile budget from 256 MiB to 128 MiB. It retains the 1,048,576-token ceiling, full KV pool, DSpark block five, static fraction 0.923, eight active requests and the existing long-admission policy. Smaller tiles reduce temporary allocation at the cost of more score operations. The results above record the observed performance and stability; the cold preparation time increased compared with the rejected trial.

The source change is fenced to the exact runtime module hash. Before model startup, four-GPU reference tests compare the tiled calculation bit-for-bit with the original and check that inputs remain unchanged. Startup alone is insufficient: repeat actual DSH 256K and near-1M retrieval/output, overlapping short requests, cached continuation, real tools and history preservation. Keep the failed 256 MiB trial and previous qualified checkpoint separately available for review and rollback.

## Operational lessons retained from the trials

The first 128 MiB initialization passed its GPU reference calculations, but an operator-side DNS/API connection failure interrupted observation. The original helper incorrectly rolled back on that connection error. This is not evidence that the 128 MiB model failed: its full DSH test had not started. The rollback and its additional initialization time remain part of the trial record.

The revised workflow retries bounded read-only operator calls and distinguishes loss of visibility from an observed model crash, restart, failed calculation or incorrect response. An operator-channel exception preserves the candidate for independent inspection rather than automatically restarting it. A subsequent attempt also refused to proceed while the restored baseline's inference endpoint was still initializing; the continuation waits for readiness and then refreshes user-idle and admission checks before the controlled handover.

Trial monitoring records operator-read failures separately from model-generation changes. Repeated loss of visibility can stop the disposable synthetic trial, but does not establish a GPU defect or authorize cancellation of a real user's work. Exact configuration snapshots, original failed results and native session records are retained privately; public summaries contain no credentials or user conversation content.
