# End-to-end 1M rollout: implementation and actual acceptance

## Why the previous request was incomplete

The model server was configured for 1,048,576 tokens, but the production
LiteLLM callback and DSH web profiles remained at 131,072. Earlier backend
tests did not finish the requested product rollout. The 128K stress test is
valid for that route; it does not establish DSH 1M operation.

## Candidate implementation

`DSH 1M canary → LiteLLM 1M canary → existing four-H100 SGLang server`

The canaries have no real user workspace/history mounts and are not selected
by the production Services. The existing inference-only Secret reference is
used inside Kubernetes. Credentials are not exported. NetworkPolicies deny
unsolicited ingress and restrict the DSH candidate to its inference candidate.

The candidate guard calls the running backend's `/v1/tokenize` endpoint with
messages, tools and template options. It requires the returned 1M model limit,
counts the actual envelope, normalizes output-limit aliases, caps output at
8,192 and keeps 256 tokens in reserve. Counting failure rejects dispatch.
This is not a character estimate. Unsupported request shapes fail explicitly.

One request above 128K is admitted at a time. A process-shared lease is held
until response/stream completion, cancellation or failure. Short requests do
not acquire that lease. The waiting deadline is 300 seconds; exhaustion
returns a retryable 429. This policy requires one gateway replica; it is not a
distributed admission controller. It does not guarantee latency for cold
DSH requests whose tool/system prefix itself needs chunked prefill.

The candidate web profile declares 1,048,576 context and 8,192 output.
Automatic compaction is configured at ratio 0.875, with 65,536 headroom and an
8,192 summary budget. The normal calculated threshold is 917,504 estimated
tokens. Actual manual/automatic compaction and persisted replies must still
be tested; configured values alone do not establish those behaviors.

## Failed trial preserved

The first current-scheduler candidate test returned the required response for
256,046 input tokens in 113.638 seconds. Three short replies completed during
the request in 0.477–1.094 seconds. The subsequent 512K stage failed and the
shared model process restarted at 13:07:43 UTC. The test stopped before 1M.

The failure was a scheduler assertion, not an observed CUDA OOM. The pinned
`PrefillAdder.add_one_req` accepts `has_chunked_req` but could nevertheless
create another chunked request from V2's reserved interactive budget. The
scheduler then asserted `self.chunked_req is None` while a long prompt still
owned that slot. The raw failure and completed measurements are preserved in
[the stopped trial](context-evidence/current-1m-canary-20261016.json).

The V3 guard defers the second chunked branch through upstream cleanup. A
complete short prefill that fits the available budget is still admitted.
Actual pinned-method branch execution reproduced the original second-owner
decision and verified deferred long, admitted short, initial long admission,
and refusal when the pinned source hash changes. These are isolated admission
tests, not GPU or end-to-end acceptance.

[Branch test](context-evidence/chunk-owner-unit-20261016.json) ·
[mounted source hash](context-evidence/chunk-owner-mounted-20261016.json) ·
[Linux guard lifecycle tests](context-evidence/long-context-guard-linux-unit-20261016.json)

## Rollback and acceptance gates

### Current V3 and cache results

After the guard was installed, the ordinary production route returned the
exact sequence in 3.683 seconds. The isolated DSH agent also completed a real
authenticated request, persisted its exact assistant reply, reported 7,561
input tokens including its normal system/tools, and declared the composed
1,048,576 context. This small request does not establish large-context use.

The uninterrupted V3 trial then completed **512,047 input tokens in 378.306
seconds**, with three tiny API probes in 0.617–0.899 seconds and no model
restart. However, a real DSH request with 7,560 input tokens waited **368.715
seconds**. A scheduler lane for <=512 uncached tokens does not by itself keep
cold DSH requests interactive. This failed product-responsiveness condition
is retained explicitly, rather than hidden by the successful tiny probes.

An additional synthetic prefix-cache test reused 8,192 tokens in the next
16,384-token call, then reused 16,384 in the 24,611-token call. A final Chat
Completions call using that same prompt returned exactly `CACHE_WARM_OK` in
0.286 seconds. This establishes cache feasibility, not full 1M acceptance.

The revised candidate therefore warms the original tokenized prompt through
completed **2,048-token extensions**, discarding each intermediate one-token
output and yielding between calls. The final unmodified chat request reuses
the computed prefix. No intermediate text is executed as a tool or inserted
into history. Cache reuse is checked after every step; loss stops the warmup
without a monolithic retry. One outstanding small step may finish after
client cancellation; the remaining loop stops. Warming consumes additional
internal model calls and is separate from user-visible output throughput.

In the first warmed-256K run, a real cold DSH request completed in **4.052
seconds** while the longer candidate remained active. Completion of the long
run, larger warmed inputs, compaction and deployment are still pending at
this source checkpoint. The new image source declares 1M; production users
continue on the previous image and 128K policy until acceptance passes.

[V3 512K trial](context-evidence/current-1m-v3-512k-20261016.json) ·
[DSH wait during that trial](context-evidence/dsh-1m-agent-during-512k-20261016.json) ·
[prefix-cache feasibility](context-evidence/prefix-warming-feasibility-20261016.json) ·
[DSH reply during warmed work](context-evidence/dsh-agent-during-warmed-256k-20261016.json)

The pre-change model Deployment and original scheduler ConfigMap are retained
privately in `outputs/rollback-chunk-guard-20261016`. The original ConfigMap
has not been overwritten. No user histories or workspace files are migrated.
The production DSH/LiteLLM 128K route remains unchanged while candidates are
qualified. The model arguments remain 1M, memory 0.90, running cap 16,
prefill chunk 1,024, maximum prefill 2,048 and decode interval four.

Acceptance requires an actual ordinary inference response after recovery,
progressive current-profile large requests, persisted DSH assistant replies
with returned token usage, tool execution, compaction, short-request latency
during long work, and post-test recovery/absence of new model errors.
Do not label the candidate as deployed end-to-end 1M until those gates pass.
