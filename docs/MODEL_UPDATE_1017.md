# DeepSeek-V4.1-Flash-1017 update

The [17 October release](https://api-docs.deepseek.com/news/news261017/) is a new checkpoint, not an automatic update to our existing local weights. The local deployment must download and validate the weights, load them and repeat the affected tests. The existing public model aliases remain stable for DSH, Claude Code and TrueForge.

## Pinned candidate

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

## Acceptance checks

1. Read back the running checkpoint path, immutable image, runtime source hashes, 1M context and DSpark settings.
2. Verify ordinary DSH answers, persisted content, streaming, tool calls and follow-up turns.
3. Verify 1, 2, 4, 8 and 16 concurrent short clients, recording queue time separately from output speed. The active GPU request cap remains eight.
4. Progress through 256K and near-1M input with known answers distributed through the material. Keep short requests running alongside long work. Check retries, allocation warnings and restarts.
5. Verify cached continuation and an actual controlled file create/read/delete tool operation. Confirm user history and workspace preservation independently.
6. Publish checkpoint-specific measurements. Earlier checkpoint timing and token-rate measurements remain historical results and must not be relabelled as results for this candidate.

## Status

19 October: release and pinned metadata reviewed; live earlier checkpoint confirmed; configuration and tokenizer byte equality verified; cache expansion completed; candidate download started. All 55 official reference-encoding tests passed after supplying the complete official fixtures and using UTF-8. A server-side dry-run confirmed that the candidate changes only the model path. The candidate has not been selected by the live model and has no new inference qualification yet. See the current performance guide for the earlier checkpoint's accepted results.
