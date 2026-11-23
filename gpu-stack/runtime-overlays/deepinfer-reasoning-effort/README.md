# DeepSeek default: thinking on, reasoning effort low (overlay `deepseek-thinking-low`)

Applied by `scripts/apply_engine_overlay.py --overlay deepseek-thinking-low` through the pipeline stage
`ApplyDeepseekThinkingLowOverlay` (commit-message flag `[apply-deepseek-thinking-overlay]`; plan-only without it).
Test only. Evidence: ledger rows LANE6-DEEPSEEK-VISION-LOW-THINKING-VERIFY-20261122 and the overlay's own evidence artifact.

## What changes (one patch, one pod recreation)

1. `serve/openai_server.py` is replaced through a content-addressed immutable ConfigMap and a single-file `subPath` mount.
   Predecessor = the live file, sha256 `fa20ca45acc7f561aa6106d68792933376a0daada8f14ad3bc91051f8e42cfde`.
   Successor (this folder) = sha256 `68d6776843dff30f58f99234d14852fbe8fef03cc97f53382402e0e3901113fb`.
   It adds `--reasoning-effort` (default `high`, i.e. today's behaviour when the flag is absent) and passes `reasoning_effort`
   (request `chat_template_kwargs.reasoning_effort`, then top-level `reasoning_effort`, then the flag) to the checkpoint's
   `encode_messages`. Nothing else differs.
2. The container command changes `--thinking-mode chat` to `--thinking-mode thinking --reasoning-effort low`; every other token
   is pinned to the live post-memory-trim command (0.915, 131072, max-num-seqs 4).

## What does not change

* Vision: the checkpoint's ViT is already served; image input works today (no flag, no extra memory).
* Memory and KV: same weights, same pool, same max-model-len and max-num-seqs.
* A request with `chat_template_kwargs.thinking=false` (SMP sends it on every call) still gets plain chat mode.

## Caller impact

Callers that do not send `thinking:false` now get reasoning (`reasoning_content`) and the extra tokens count against their
`max_tokens`; a small budget can end with `finish_reason=length` (the Azure r2 lesson).

## Rollback

The pipeline re-patches automatically if the rollout does not verify. Manual: restore the command from `PRIOR_COMMAND` in the
overlay class, delete the `reasoning-effort-successor` volume and the `/work/runtime/serve/openai_server.py` mount.
