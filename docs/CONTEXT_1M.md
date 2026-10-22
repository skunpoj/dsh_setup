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
| Serialized text-work threshold | Counted input plus reserved output above 32,768 |
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
This classifies the complete conversation, not just the latest typed prompt.
One text request owns the expensive-work lane; one additional request can wait
for up to 1,500 seconds. Further requests receive a busy response. Smaller text
requests remain concurrent. The separate 128K multimodal capability boundary
is unchanged; the text preparation path does not qualify multimodal fairness.

The forwarder creates its own soft cache reference and removes client-supplied
cache/session controls. The backend reference expires after 3,900 seconds; the
forwarder's complete preparation/response lifecycle is bounded to 3,300 seconds.
Stop drains owned work and closes that reference before releasing its lane.
This cache reference improves reuse; it is not a security boundary or a promise
that a prefix can never be evicted. The rendered engine enables the required
session-aware radix-cache support.

For the pinned LiteLLM image, the streaming compatibility shim preserves the
trusted loopback admission error as HTTP 429. It does not reclassify arbitrary
provider errors. Its SDK-source fingerprint must match or startup refuses;
qualify the reader again before changing that dependency.

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

For a private test origin, use
[`build_budget_qualification_overlay.py`](../scripts/build_budget_qualification_overlay.py)
with the reviewed transport/forwarder source fingerprints and exact canonical
origins. It never edits its inputs or deploys a workload. The private test gate
rejects counted inputs of at least 950K with an output reservation below 512
before preparation. That minimum applies only to qualification, not ordinary
production calls. Verify the final forwarding record retains the intended
output allowance before beginning a long test. A configured ceiling does not
prove the client actually reserved it. Generated overlays contain site settings
and belong outside the public repository.

The repository supplies a complete configuration and tests, not a fresh four-GPU
benchmark on every reader's hardware. See official [SGLang server arguments](https://docs.sglang.io/docs/advanced_features/server_arguments)
and [LiteLLM production deployment](https://docs.litellm.ai/docs/proxy/deploy).
