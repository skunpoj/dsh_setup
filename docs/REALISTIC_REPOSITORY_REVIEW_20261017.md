# DSH — Real Repository Review: Generated Response Acceptance

## Result

**The unedited DSH-generated response passed this frozen-source acceptance task after three source-backed DSH correction turns. No editorial citation or narrative repairs were applied to the accepted response.** The actual DSH agent used **1,007,329 input tokens** and generated **3,798 output tokens**, including a **1,647-word engineering narrative** and a generated seven-claim evidence ledger. Its actual saved prompt and response were read back.

| Acceptance check | Verified result |
|---|---|
| Exact canonical answer values | 15/15 |
| Complete answer/source/quotation conditions | 15/15 |
| Narrow narrative citation ranges | 52/52, at most 12 lines |
| Known narrative source-branch regressions | 7/7; checked in both generated ledger and narrative |
| Narrative source review | Complete; zero remaining findings in this response |
| Editorial changes to accepted output | **0** |
| Requested narrative length | 1,647 words; required 1,400–1,800 |
| Combined acceptance | All recorded conditions passed |

This is a targeted regression test, not a guarantee of general model accuracy. The prompt explicitly addresses known earlier failure patterns. “Fully accepted” here means this response satisfied the declared mechanical and source-review criteria; it does not mean every future DSH response is safe or accurate, or that an external assessor approved it.

## Why the previous result was not accepted, and what changed

The previous generated narrative still cited candidate mount assertions as proof of profile-hash restoration, and candidate construction as proof of a later concurrent-edit comparison. Correcting only the displayed publication did not fix that generated output. That prior raw response remains failed and unchanged in the [archived reviewed publication](REALISTIC_REPOSITORY_REVIEW_PRIOR_EDITORIAL_20261017.html).

The fresh cold run still failed narrative/ledger checks, and is preserved. Subsequent correction requests supplied source-backed error feedback and short excerpts already present in the archive. DSH generated the accepted response itself; its text was not repaired afterward. This is assisted correction, not a blind one-shot accuracy benchmark. The new DSH review prompt requires a generated claim ledger that separates these operations. The validator checks actual restore-branch hash/byte assertions, mount-list preservation, the later live-spec comparison, container-list append, HTTP tokenizer invocation, scoped transport-fixture assertions, and acknowledged probe-abort conversion. It requires the same actual branch in the narrative, so a correct ledger cannot mask a wrong narrative citation. Separate Codex source review then checks what each cited span establishes; line existence and exact quotation alone do not establish semantic support.

The acceptance record is bound to original assistant-text SHA-256 `820431546669c68a5a642799626673e064c69a0e5eaf730bbc11ec9e6bd1f80b`. The accepted response is published byte-for-byte in the raw artifact. The narrative below retains its wording; source identifiers are converted to pinned links for display, without rewriting claims, quotations or citation spans. This source review is not external assessor sign-off.

## Actual test path, context and timing

The path was **actual DSH agent RPC → internal LiteLLM → final-wire guard → SGLang → shared four-GPU model**, using an explicitly allowlisted disposable runtime and empty state/workspace volumes. It was not a Claude Code, TrueForge or manual browser-interface run. No user histories, ownership, mounts or shared inference settings were changed.

The same **239 current source blocks and 99 labelled historical revisions** were used, with no synthetic token filler. Identical whole-file content is deduplicated, while historical revisions still overlap. Frozen versions are DSH `7f477341a5429c7dfe393dffe89f0cdef2887333` and GPU_server `81f42dc522f51e9e940ade181b78945984b189ce`. CURRENT means those frozen versions, not a fresh deployment claim. The cold prompt excluded previous responses and the reference answer key. The correction retained its own failed draft in the same conversation and received explicit source-backed feedback, without the answer key. The cold submitted prompt hash `97157d7fc2f7695a71842f2a30e014d230013b2a749d5b555d5c8c1d112a7424` was independently reconstructed from pinned Git objects. The correction request's feedback hash is `f3d9384bdb7aee950e175507bb3abddabcf12f624c8e5e5c080d6534b7e8a9bf` and its exact text is retained separately.

| Measurement | Observed result |
|---|---|
| Input / output / total | 1,007,329 / 3,798 / 1,011,127 tokens |
| Complete DSH turn | 123.28s — 2m03s |
| Before prefix preparation | 2.713s |
| Prefix preparation | 1.061s; mode `bounded-cache-probe` |
| DSH-reported output phase | 116.663s, 3,798 tokens |
| Short DSH replies during admitted work | 2, exact and persisted, in pairs; **2.03–2.03s** |
| Replies during generation itself | 2, included above |
| DSH retry events | 0 |
| Model continuity | Same image/pod; restart count unchanged |
| Recovering mapping-OOM warnings | 4 in the admitted shared-model log window |
| Checked fatal log signatures | 0 |
| Minimum sampled GPU free memory | 570 MiB, not a transient-minimum guarantee |

Prefix preparation is correlated by final input count and timing, not a globally unique request ID. Memory headroom remains tight. One long request is admitted at a time; paired short responsiveness is observed, not guaranteed, and this is not two concurrent full-1M requests or a sustained-load SLA. The first generated correction passed 7/7 branch checks but still had other citation errors and a broad range. The second passed mechanical checks but source review found two remaining claim/citation mismatches. Their original responses and rejections remain retained. Only the final generated response is accepted. Cache reuse is conditional: the previous campaign included both a fast cached correction and a later full-prefix rebuild. Those observations remain in the archive rather than being replaced by this result.

The initial cold turn used **993,988 input / 4,067 output tokens** and took **1342.61s**. Its 1707-word draft passed all fifteen answer checks but failed narrative/ledger validation. During that cold turn, 20 short replies completed at 4.03–12.07s. The table above describes the final accepted correction turn; its preparation mode and timing are reported separately rather than treating cache reuse as guaranteed.

## Generated claim ledger — unchanged content

### ROLLBACK_HASH

In the restore branch, the saved profile SHA-256 is verified against its stored digest, the profile is written back via a temporary file and os.replace, and the restored bytes are asserted equal to the original.

[S0010:L46-L51](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/promote_1m_runtimes.py#L46-L51)

```text
assert profile.read_bytes()==original
```

### MOUNT_PRESERVATION

The candidate builder compares its copied pod volumes and the first container's volumeMounts with the original deployment's corresponding lists and asserts equality.

[S0010:L70-L71](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/promote_1m_runtimes.py#L70-L71)

```text
assert pod['volumes']==original['spec']['template']['spec']['volumes']
```

### CONCURRENT_EDIT_REFUSAL

The proxy promotion path re-reads the live gateway deployment and raises an error refusing to continue when its spec differs from the planned original.

[S0304:L151-L153](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/promote_1m_proxy.py#L151-L153)

```text
raise RuntimeError('Gateway changed after plan; preserve concurrent edits')
```

### SIDECAR_INSERTION

The candidate builder appends the context-forwarder sidecar object to the pod's container list.

[S0304:L100-L100](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/promote_1m_proxy.py#L100-L100)

```text
pod['containers'].append(sidecar)
```

### TOKENIZER_CALL

count_request builds an HTTP Request to the configured tokenizer URL, sends the JSON-encoded payload and parses the response.

[S0308:L43-L48](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L43-L48)

```text
req = urllib.request.Request(TOKENIZER, data=json.dumps(payload).encode(),
```

### TRANSPORT_SCOPE

The transport fixture asserts the managed origin receives one-hour header timeout while the listed unrelated origins keep their own options unchanged.

[S0357:L5-L12](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/tests/test_managed_inference_transport.js#L5-L12)

```text
assert.equal(seen[0][0].headersTimeout,3600000)
```

### CACHE_PROBE_ABORT

On a timeout, if the abort request was acknowledged, warm_prefix raises CacheProbeMiss instead of a generic cancellation error; an unacknowledged cancel raises a stop-escalation error.

[S0308:L91-L95](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L91-L95)

```text
raise CacheProbeMiss('Cold prefix probe cancelled') from error
```


## Accepted DSH-generated narrative — unchanged wording

### DSH Long-Context Execution: Implementation-to-Claim Alignment

#### 1. Scope and evidence discipline

This review reconciles implementation and recorded claims in the frozen CURRENT sources. Four categories are kept separate throughout: frozen implementation/configuration, recorded test observation, historical checkpoint, and recommendation. CURRENT denotes the frozen repository version; it is not fresh deployed behavior, and nothing here was executed against Production. Short sentinel strings confirm only that a reply was exact, never that a model is accurate, and eight tokens do not constitute an accuracy benchmark. No SLA, guarantee, or two-full-1M acceptance is asserted, because the frozen sources do not establish one.

#### 2. Execution path, defaults and final-wire counting

The request path begins at DSH, passes an output-alias guard and a loopback-only proxy, and reaches the SGLang backend. The gateway output guard rejects endpoint/provider overrides, requires chat messages, and clamps the output aliases to 8,192 before they leave that hook [S0367:L13-L21](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/gateway_output_guard.py#L13-L21). The forwarder then counts the final envelope with the running backend tokenizer, failing closed if counting is unavailable [S0196:L88-L94](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/context_forwarder.py#L88-L94).

The counting call itself is a real HTTP invocation: `count_request` constructs a Request against the tokenizer URL with a JSON-encoded payload and parses the response [S0308:L43-L48](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L43-L48); it validates that the returned count is an integer, that the model limit equals the context constant, and that the token IDs are a list of the same length, refusing otherwise [S0308:L62-L67](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L62-L67). This matters because defaults can change the token sequence. `normalize_conditioning` materializes an omitted function `strict` as Boolean false [S0272:L9-L12](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/context_envelope.py#L9-L12) and `continue_final_message` as Boolean false via `setdefault` [S0272:L4-L5](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/context_envelope.py#L4-L5). The recorded alignment observation explains why: an earlier tool request counted 7,689 tokens while inference processed 7,561, so warming one sequence could not guarantee a reusable prefix for the other [S0346:L130-L130](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L130-L130). The corrected live comparison is described as a fresh alignment check, explicitly not another near-1M capacity test [S0346:L134-L134](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L134-L134).

The gateway output guard's own clamp is `data['max_tokens'] = min([8192]+limits)` after the alias list is normalized [S0367:L20-L21](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/gateway_output_guard.py#L20-L21), while the long-context guard defines `CONTEXT = 1048576`, `OUTPUT = 8192` and `RESERVE = 256`, and derives available output as context minus reserve minus counted input, refusing when that value is below one [S0308:L19-L21](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L19-L21)[S0308:L185-L193](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L185-L193). The aliases also appear in the runtime policy: the 1M branch names the model with a `1M` label and caps output at 8,192 [S0005:L15-L17](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/configure_runtime_context.js#L15-L17).

#### 3. Long-request admission versus ordinary concurrency

Admission is a process-shared file lock inside a single LiteLLM replica, not any notion of repository sharing. The module docstring records the design intent: run in one LiteLLM replica, hold the process-shared flock until the stream closes, including cancellation or failure, and let ordinary requests avoid waiting on that lock [S0308:L3-L5](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L3-L5). A recorded deployment-guide note states that one gateway replica owns admission and that scaling replicas requires distributed ownership, since an independent lock would not enforce a shared long-request limit [S0289:L50-L50](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/END_TO_END_1M_ROLLOUT_20261016.md#L50-L50). These are statements about replica count and a lock file, not about Git repositories or source forks.

Whether a request is long is decided by comparing counted input plus chosen output against `LONG_THRESHOLD = 131072` [S0308:L22-L23](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L22-L23). The guard compares that sum against the threshold and, for a long request, removes any client-supplied metadata lease key before generating the real one [S0308:L198-L201](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L198-L201). It then acquires a server-side lease; the key is created server-side and any client-supplied metadata key is first removed by that same block [S0308:L194-L197](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L194-L197). Acquisition loops on a non-blocking flock with a deadline of 300 seconds and raises a 429 with a 30-second retry hint when exhausted [S0308:L144-L153](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L144-L153). Release is wired to the success and failure hooks [S0308:L211-L218](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L211-L218) and to the streaming-iterator hook's `finally` path [S0308:L220-L226](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L220-L226).

A recorded live check used a deliberately held admission lock rather than a fabricated GPU workload; the real authenticated gateway returned HTTP 429 after 300.36 seconds while ordinary DSH replies continued [S0346:L22-L26](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L22-L26). The source labels this as validating admission behavior and explicitly notes it is not two actual near-1M GPU requests [S0346:L102-L102](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L102-L102). The backend's running-request ceiling of 16 [S0280:L89-L90](https://azuredevops.bot.or.th/BOTCollection/da_Team_DA_Board/_git/GPU_server?path=%2Fdeployment%2Fvllm%2F04-vllm-deepseek-v4-1-flash.yaml&version=GC81f42dc522f51e9e940ade181b78945984b189ce&line=89&lineEnd=91&_a=contents) is described in the qualified operating boundary as an admission ceiling rather than a promise about 16 maximum-length requests [S0346:L50-L50](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L50-L50).

#### 4. Cold, cached and conditional latency and memory

The cache path has three distinct branches, and the constants alone do not describe them. With a bounded probe configured, the guard calls the warm helper for the whole ID list; on `CacheProbeMiss` it falls through to incremental preparation, while a successful probe whose prompt-token count does not match raises a hard error [S0308:L115-L126](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L115-L126). When the probe times out and the abort request was acknowledged, the helper raises the typed `CacheProbeMiss` [S0308:L91-L95](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L91-L95); an abort that is not acknowledged instead raises a stop-escalation error rather than retrying blindly [S0308:L93-L94](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L93-L94). Incremental preparation then extends the prefix in `WARM_STEP = 2048` blocks, refuses when cached tokens fall more than 512 below the previous extension, and yields between steps [S0308:L26-L27](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L26-L27)[S0308:L127-L138](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L127-L138). The warming request IDs are generated inside `warm_prefix` [S0308:L71-L76](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L71-L76) and are unrelated to the long-admission lease keys created in the pre-call hook.

On the streaming handoff, the forwarder sets a first-content deadline of 15 seconds for the guarded long case [S0196:L152-L153](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/context_forwarder.py#L152-L153) and emits a typed `context_cache_handoff_failed` error payload when that deadline lapses [S0196:L175-L179](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/context_forwarder.py#L175-L179). The regression file covers that deadline separately, asserting that only the request's own ID is aborted and that the lease is released [S0279:L175-L183](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/tests/test_context_forwarder.py#L175-L183).

The memory evidence must be read at the right layer. The model container's Kubernetes resources request `memory: 256Gi` and limit it to `512Gi`, alongside four GPUs [S0280:L133-L141](https://azuredevops.bot.or.th/BOTCollection/da_Team_DA_Board/_git/GPU_server?path=%2Fdeployment%2Fvllm%2F04-vllm-deepseek-v4-1-flash.yaml&version=GC81f42dc522f51e9e940ade181b78945984b189ce&line=133&lineEnd=142&_a=contents); these are host/container RAM fields, not GPU memory, KV cache or temporary attention workspace. The Engram host-table offload is configured through separate environment variables in that manifest, at the lines that declare them [S0280:L113-L120](https://azuredevops.bot.or.th/BOTCollection/da_Team_DA_Board/_git/GPU_server?path=%2Fdeployment%2Fvllm%2F04-vllm-deepseek-v4-1-flash.yaml&version=GC81f42dc522f51e9e940ade181b78945984b189ce&line=113&lineEnd=121&_a=contents). The recorded qualification repeatedly reports thin GPU memory: 1,460 recovering allocator mapping warnings with a minimum reported free memory of 9.75 MiB while attempting a 20 MiB mapping [S0346:L11-L11](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L11-L11), and the qualified operating boundary admits one request above 128K at a time with two full simultaneous 1M requests not established [S0346:L50-L50](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L50-L50).

Recorded latency is likewise bounded. The CURRENT README records a cold DSH run returning the exact persisted answer at 1,007,689 input tokens in 19m34s [S0087:L5-L5](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/README.md#L5-L5), and a write/read tool continuation at 1,008,103 input tokens passing in 20.16 seconds [S0087:L5-L5](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/README.md#L5-L5). Those are recorded observations from that snapshot, not a fresh test and not an SLA. Historical checkpoints retain different guardrails: an older README copy still described a 131,072-token guardrail and compaction near 98,304 for the DeepSeek aliases [S0262:L206-L209](https://github.com/skunpoj/dsh_setup/blob/c961fa0151a8ed080c92a710da330f257d31444c/README.md#L206-L209), and the earlier near-1M backend success belonged to a previous scheduler profile rather than current near-1M fairness [S0333:L72-L72](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/SCHEDULING_FAIRNESS_20261015.md#L72-L72).

#### 5. Compaction

Compaction policy is selected per runtime context. The 1M branch chooses a `thresholdRatio` of 0.875 and 65,536 `headroomTokens`, while the 128K branch keeps 0.75, and existing model policies for the same provider and aliases are filtered out before the new ones are pushed [S0005:L28-L33](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/configure_runtime_context.js#L28-L33). The formula recorded in the guide is `floor(min(context × ratio, context − reserved output − headroom))`, evaluated as 917,504 estimated tokens for the 1M case [S0346:L195-L199](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L195-L199). Compaction is a between-steps estimate, not an exact final-wire count, so a single oversized tool result or attachment can still reach the request guard first and be refused [S0346:L201-L201](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L201-L201). That limitation is a configuration/design statement; the guide does not certify that every historical session compacts successfully.

#### 6. Rollback and a cautious recommended verification workflow

Rollback is implemented, not merely documented. In the restore branch, the saved profile's SHA-256 is verified against its stored digest, the profile is written back through a temporary file and `os.replace`, and the restored bytes are asserted equal to the original [S0010:L46-L51](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/promote_1m_runtimes.py#L46-L51). The candidate specification itself asserts that the copied pod volumes and the first container's volumeMounts equal the originals, so a routine rollout compares these lists before patching [S0010:L70-L71](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/promote_1m_runtimes.py#L70-L71). That comparison is a specification equality check on the candidate manifest; it does not prove that no future change could repoint storage, that every user file is preserved, or that all concurrent writes are protected.

The proxy promotion path additionally re-reads the gateway deployment after preparing its immutable ConfigMap and raises an error refusing to continue when the live spec no longer matches the plan, preserving concurrent edits [S0304:L151-L153](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/promote_1m_proxy.py#L151-L153). The same builder appends the context-forwarder sidecar to the pod container list [S0304:L100-L100](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/promote_1m_proxy.py#L100-L100), and the transport fixture asserts that the managed origin's header timeout is extended to one hour while the listed unrelated origins keep the caller's own options unchanged [S0357:L5-L12](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/tests/test_managed_inference_transport.js#L5-L12). This fixture is a source-level test definition; it is not evidence that the test was executed here, and its assertions cover the managed origin plus the specific listed unrelated-origin cases rather than every possible origin.

Recommended operational workflow, offered as guidance rather than recorded fact: verify the frozen executable definitions first — the callback constants, normalization defaults, admission threshold and wait, warming step and probe, and handoff deadline — without touching a live runtime. Then reproduce the frozen regression suites in a disposable namespace, and if a live check is authorised, use only the named disposable probe pods, capture the backend tokenizer output, and save the raw evidence under a new filename rather than re-using an older pass [S0346:L104-L106](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L104-L106). Keep a compatible old image and the in-PVC profile backup, and confirm the saved hash matches before starting the old image on rollback [S0010:L46-L51](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/promote_1m_runtimes.py#L46-L51). Read back the running image, mounted configuration and a real client turn afterwards, because configuration, source tests, deployment and user-facing behavior remain distinct categories [S0289:L54-L56](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/END_TO_END_1M_ROLLOUT_20261016.md#L54-L56). Do not describe the route as delivered end-to-end 1M until those gates pass, and do not treat one long request as evidence that two maximum-length requests fit.

## Persistence, cleanup and reproducible records

The actual submitted input matched the saved DSH conversation. The disposable session archive contained **86 files**; the downloaded archive hash and session-only paths were verified before pod removal. The pod was then confirmed absent. Ordinary authenticated inference returned the expected answer in **0.340s**, the admission slot was free and the model identity/restart count remained unchanged. Runtime deletion is not used as proof of cancellation.

[Generated correction comparison](context-evidence/realistic-repo-grounded-generated-diff-20261017.json) · [Original unedited assistant output](context-evidence/realistic-repo-grounded-original-assistant-text-20261017.txt) · [parsed model response](context-evidence/realistic-repo-grounded-model-response-20261017.json) · [answer/citation checks](context-evidence/realistic-repo-grounded-exact-checks-20261017.json) · [seven branch regressions](context-evidence/realistic-repo-grounded-narrative-regressions-20261017.json) · [source review](context-evidence/realistic-repo-grounded-source-review-20261017.json) · [combined acceptance](context-evidence/realistic-repo-grounded-acceptance-20261017.json) · [performance](context-evidence/realistic-repo-grounded-performance-20261017.json) · [reconstruction specification](context-evidence/realistic-repo-grounded-source-specification-20261017.json) · [cleanup](context-evidence/realistic-repo-grounded-cleanup-20261017.json) · [runtime comparison](context-evidence/realistic-repo-grounded-runtime-20261017.json) · [review protocol](REPOSITORY_REVIEW_CITATION_PROTOCOL.md) · [failed cold draft](context-evidence/realistic-repo-grounded-cold-draft-response-20261017.json) · [cold checks](context-evidence/realistic-repo-grounded-cold-draft-checks-20261017.json) · [cold ledger failures](context-evidence/realistic-repo-grounded-cold-draft-regressions-20261017.json) · [cold timings](context-evidence/realistic-repo-grounded-cold-draft-performance-20261017.json) · [cold source review](context-evidence/realistic-repo-grounded-cold-draft-source-review-20261017.json) · [final correction feedback](context-evidence/realistic-repo-grounded-correction-feedback-20261017.txt) · [first correction response](context-evidence/realistic-repo-grounded-first-correction-response-20261017.json) · [first correction checks](context-evidence/realistic-repo-grounded-first-correction-checks-20261017.json) · [first correction branch checks](context-evidence/realistic-repo-grounded-first-correction-regressions-20261017.json) · [first correction source review](context-evidence/realistic-repo-grounded-first-correction-source-review-20261017.json) · [first correction timing](context-evidence/realistic-repo-grounded-first-correction-performance-20261017.json) · [first correction feedback](context-evidence/realistic-repo-grounded-first-correction-feedback-20261017.txt) · [second correction response](context-evidence/realistic-repo-grounded-second-correction-response-20261017.json) · [second correction checks](context-evidence/realistic-repo-grounded-second-correction-checks-20261017.json) · [second correction source review](context-evidence/realistic-repo-grounded-second-correction-source-review-20261017.json) · [second correction feedback](context-evidence/realistic-repo-grounded-second-correction-feedback-20261017.txt) · [second correction timing](context-evidence/realistic-repo-grounded-second-correction-performance-20261017.json).
