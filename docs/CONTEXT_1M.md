# 1M context: architecture, tuning and qualification

The complete path is DSH → authenticated LiteLLM → loopback context forwarder →
SGLang. Raising only the model server's context limit does not enable the full
product. The supplied profile declares 1,048,576 total tokens at all relevant
layers; exact final-wire tokenization includes message/tool conditioning.

| Control | Reference value |
|---|---:|
| Total context | 1,048,576 |
| Maximum output | 8,192 |
| Proxy reserve | 256 |
| Long-request threshold | Above 131,072 |
| Admitted long requests | One per gateway pod |
| Backend running cap | 16, subject to aggregate capacity |
| Static memory fraction | 0.90 |
| Prefill chunk | 1,024 |
| Maximum prefill tokens | 2,048 |
| Decode interval | Four |
| DSH compaction ratio | 0.875, approximately 917,504 estimated tokens |

At maximum output reservation, counted input must be at most 1,040,128 tokens.
Compaction is an earlier estimate-based product control, not a substitute for
wire budgeting. The guard rejects unsupported near-1M image conditioning rather
than claiming image embeddings can be prepared from text-token IDs.

Long preparation runs in bounded steps to permit ordinary requests to progress.
The pinned scheduler overlays reserve short-prefill space and preserve a single
chunked-request owner. Both scripts verify original source hashes before writing
overlay files; unknown images fail closed. They are not interchangeable patches
for arbitrary newer SGLang releases.

Small chunks reduce temporary attention-memory demand but can increase prefill
overhead. Increasing static KV allocation alone can reduce temporary workspace
and cause OOM despite apparently sufficient cache slots. GPU cache capacity is
shared across active requests; 16 running slots do not imply 16 full-1M sessions.
One very long request can still lower short-request throughput. There is no
guaranteed time-to-first-token or tokens/second in this reference.

## Qualify progressively

On your isolated target hardware, measure short calls, two/four concurrent short
calls, 128K, 256K, 512K and near-1M text. Count actual backend tokens; distinguish
cold preparation from cache reuse. Test short requests while long work remains
active, cancellation and lease release, output limits, real tool continuation,
streaming, compaction recall and restart recovery. Record failures and GPU
memory/restart state. Keep an accepted smaller-context rollback profile.

Use `scripts/probe_dsh_1m_agent.py` only inside a disposable runtime with synthetic
storage and an explicit test deadline. It creates a synthetic session and can
run write/read tools; do not point it at another person's history. Export only
sanitized aggregate measurements, not raw prompts, credentials or infrastructure
metadata. Full-1M stress is opt-in and can affect shared inference users.

The repository supplies a complete configuration and tests, not a fresh four-GPU
benchmark on every reader's hardware. See official [SGLang server arguments](https://docs.sglang.io/docs/advanced_features/server_arguments)
and [LiteLLM production deployment](https://docs.litellm.ai/docs/proxy/deploy).
