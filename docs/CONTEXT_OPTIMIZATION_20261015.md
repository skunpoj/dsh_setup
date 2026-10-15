> Repository mirror of GPU_server `test-evidence/context-optimization-20261015.md`. Model manifest and rollback references below belong to GPU_server; bundled JSON response copies are in [context-evidence](context-evidence/). The initial raw incident logs and large synthetic inputs are not bundled. This update does not rerun inference or revise historical PDF/HTML exports.

# DeepSeek-V4.1-Flash context optimization evidence

Date: 15 October 2026 (ICT)

Hardware: one node, four NVIDIA H100 NVL GPUs

Runtime: SGLang DeepSeek-V4.1-Flash TP=4

Final model-server profile: context 1,048,576; static memory fraction 0.90; prefill chunk 1,024; max prefill tokens 2,048; max running requests 16
User-facing guardrail during all tests: DSH and LiteLLM remained at 131,072 total tokens.

## Results

| Stage | Actual input | Result | Runtime evidence |
|---|---:|---|---|
| Initial 1M configuration, static 0.92 | Approximately 262K input tokens | CUDA OOM | Needed 1,022 MiB while GPU 3 had about 1,001.75 MiB free; model exited; recovery approximately 14 minutes |
| 256K startup, static 0.88 | No inference; startup failed | Insufficient full KV pool | DSV4 SWA reservation left about 0.27 GB; rejected before traffic |
| 256K | 250,011 tokens | `LONG_CONTEXT_OK` | Ready; restart 0; no OOM or scheduler exception |
| 512K, chunk 4,096 | 500,012 tokens | `LONG_512K_OK` | Completed, but CUDA allocator OOM warnings occurred and free memory fell to about 0.34 GiB; rejected as unstable |
| 512K, chunk 2,048 | 500,012 tokens | `LONG_512K_OK` | Ready; restart 0; no OOM or scheduler exception; observed free memory about 3.06 GiB during prefill |
| 1M, chunk 2,048 | 1,000,000-token generated body | `Internal Server Error` | Allocator OOM warnings began around 905K processed tokens; model restarted once; failed |
| 1M, chunk 1,024 | 1,000,015 tokens | `LONG_1M_RETEST_OK` | Ready; restart 0; no OOM or scheduler exception |
| Two long requests | 480,012 tokens each | `DUAL_1_OK`, `DUAL_2_OK` | Both submitted together and completed in 538.22 seconds; restart 0 |

The 512K optimized startup reported 1,150,208 aggregate token slots and approximately 8.94 GiB available GPU memory after initialization. Token slots alone did not make 1M executable because attention workspace was exhausted during real inference.

During the dual-480K run, SGLang warned that several Triton kernels were device-loaded after serving began with only about 0.01 GiB free and recommended preloading them to avoid a possible CUDA OOM. No allocator OOM, failed response, scheduler exception, or restart occurred in that run, but the warning confirms that two near-512K requests leave negligible transient-memory headroom. This result verifies managed completion, not unrestricted parallel capacity at that size.

## Recovery and functional regression

After the failed first 1M request, the deployment was restored and verified at 512K before the smaller-chunk 1M retest. Four simultaneous short requests through LiteLLM returned `RECOVERY_1_OK` through `RECOVERY_4_OK` in approximately 0.71 seconds each. Streaming produced five events and the complete text `STREAM_OK`. A required function-call request returned `finish_reason=tool_calls` and `lookup_case` with `case_id=1213`. After the successful 1M and dual-480K tests, four more simultaneous short requests returned `POST_DUAL_1_OK` through `POST_DUAL_4_OK` in approximately 0.62 seconds each.

## Decision

The verified model-server ceiling is 1,048,576 tokens with the optimized 1,024-token prefill chunk. A near-1M request occupies essentially the complete cache, so it is an exceptional workload rather than a routine concurrency target. Short-request concurrency remained operational after the long tests. Aggregate long traffic requires admission control or queueing because the dual-480K run left negligible transient-memory headroom. The current DSH and LiteLLM user guardrail remains 131,072 until product-level compaction, admission control, and long-session behavior are deliberately changed and tested.

## Lessons and evidence limits

1. A startup KV-slot count measures cache capacity, not total executable inference capacity. Temporary attention workspace, kernel loading and allocator behavior also require GPU memory. The old 2,185,984-slot observation at static 0.92 did not establish that two 1M requests could run.
2. Increasing static reservation alone was the wrong response to the original attention-workspace OOM. Reducing it too far also failed: static 0.88 could not initialize the required DSV4 cache layout. The tested balance was static 0.90 plus smaller prefill chunks.
3. Chunking was progressively reduced from 4,096 to 2,048 to 1,024, with maximum prefill tokens 8,192 to 4,096 to 2,048. This bounded the tested prefill steps and enabled the final long request. These empirical results are specific to the recorded model/runtime, GPU layout and request patterns.
4. A returned answer is insufficient when allocator OOM warnings remain. The first 512K response was rejected as unstable despite its successful output.
5. Maximum running requests 16 is a scheduler ceiling, not a promise that sixteen long contexts fit. The final startup pool was 1,179,648 aggregate slots. Two simultaneous 480,012-token submissions completed; the tests do not prove continuous simultaneous execution or two full 1M contexts.
6. The final successful input was 1,000,015 tokens with 10 completion tokens. The configured ceiling is 1,048,576 total tokens; a request occupying the entire ceiling, a long generated answer at that size, long-context retrieval quality and sustained production load were not established by this test.
7. Streaming and function-call checks in this record ran after the 512K recovery. They were not repeated at near-1M input. Short-request concurrency was tested after the final 1M and dual-long runs, not proven latency-isolated during a near-1M prefill.
8. Retain the 128K rollback and the successful 512K configuration. Protect normal traffic with measured admission/queueing before raising the DSH/LiteLLM user budget. Preload warnings require investigation before treating maximum-length traffic as routine.

## Reproduction, source and rollback

The final runtime uses image digest `sha256:4a5d132a06a77c8331e15845f2e925adc788b00105097ad55409afa3f4fa4860`, SGLang `dev-cu13-dsv41`, TP=4 and model snapshot `dba1be0a40aa45a94ad051997016db3960a90277`. The tested profile is in `deployment/vllm/04-vllm-deepseek-v4-1-flash.yaml`; source/evidence were committed in GPU_server `60ca4d4f15af7ef525848c0dfc0f5a2d1af1fa22`.

Saved response records in this directory: `near-256k-response.json`, `near-512k-response.json`, `near-512k-response-chunk2048.json`, `near-1m-response.json` (failed response), `near-1m-response-chunk1024.json`, and `dual-480k-response.json`. These files preserve responses/usage, not complete telemetry or full request payloads. The original 262K incident and startup-failure rows are historical observations from the session record; no standalone raw response for them is bundled here. Large synthetic request bodies were not retained in Git, so this is a detailed engineering record rather than a fully reproducible benchmark package.

Original 128K rollback snapshot: `C:\Users\skunpojt\rollback-model-20261015-1305\deployment.yaml` and `litellm-config.yaml`. Read back the target before rollback and plan for model reload on the single node. Do not mistake an archived manifest for the current live state.

## Later scheduling correction

The subsequent [interactive scheduling record](SCHEDULING_FAIRNESS_20261015.md) documents the discovered blocking of normal traffic during long tests, the V1 cached-session failure and final V2 correction. The live model now uses the same context/memory/chunk limits with a reviewed scheduler overlay, mixed chunking and four decode rounds between prefills. V2 passed approximately 133K-long-request contention tests with both fresh small inputs and 24K cached histories. The original million-token result above belongs to the earlier scheduling profile; near-1M completion and latency under the new mixed-load profile have not been revalidated. The DSH/LiteLLM user guardrail remains 128K.
