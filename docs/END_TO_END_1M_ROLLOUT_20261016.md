# End-to-end DSH 1M — Rollout and Engineering Experience

## Requirement and correction

The requirement was usable 1M context through DSH, LiteLLM and DeepSeek-V4.1-Flash on the existing single four-H100 node. Earlier backend-only success left DSH/LiteLLM at 128K and did not finish that requirement. The previous candidate checkpoint is retained in [its historical file](ONE_M_CANDIDATE_CHECKPOINT_20261016.md); it is not the current status.

All 20 main private runtimes have now been upgraded to the qualified image and scoped transport, with 1,048,576 context and 8,192 output in both aliases. Actual imageIDs, numerical profiles, inference origins and owner/admin compositions were checked. The final cold request passed at 1,007,689 input tokens without retries, followed by a real tool continuation above one million tokens. The earlier successful runs and failures remain documented as engineering history; they are not presented as the final acceptance.

## Final acceptance

The final managed-transport cold test completed with **1,007,689 input + 8 output tokens in 1,170.08 seconds**, exact persisted response, **zero retries and unchanged model pod/restart count**. A same-session real write/read continuation passed at **1,008,103 input tokens in 20.16 seconds**, with actual file content/hash checked and marker removed. This qualifies the recorded application workflow, not only a backend API call.

The cold run logged **1,460 recovering allocator mapping warnings**. Their minimum reported free memory was **9.75 MiB**, against a 20 MiB mapping attempt. Checked fatal exception signatures remained zero and requests continued. A late actual admin DSH reply after warnings took 6.03s. Memory remains tightly constrained; this is not arbitrary large-concurrency or full-output acceptance. Preserve that limitation alongside the passing result.

[Final cold summary](context-evidence/final-managed-1m-acceptance-summary-20261016.json) · [Actual near-1M tools](context-evidence/final-managed-1m-tool-continuation-20261016.json) · [Running image/config provenance](context-evidence/final-managed-1m-runtime-provenance-20261016.json).

## What failed and what changed

| Experiment | Actual observation | Resulting decision |
|---|---|---|
| Older 0.92 allocation / roughly 262K | CUDA OOM despite apparent cache capacity | KV slots alone omit temporary attention workspace; retain 0.90 and small prefill chunks |
| Current V2, 512K | Scheduler assertion `self.chunked_req is None`; shared model restarted | V3 enforces one chunk owner; do not describe this as an OOM |
| V3 uninterrupted 512K | 512,047 input passed in 378.31s, but real DSH short call waited 368.72s | Tiny API probes do not establish DSH responsiveness; prepare long prefixes incrementally |
| Early pre-call warming, 500K | Warmup completed but final chat had zero cached tokens and repeated full prefill | Move counting/warming to the final outgoing envelope; stop and preserve failed trial |
| Final-envelope comparison | Tokenizer materialized `strict:false` in 26 tools and `continue_final_message:false`; chat did not | Normalize these defaults on both paths, preserving explicit values |
| Exact-ID proof | Raw counts 7,689 vs 7,561 differed; normalized IDs matched SHA256 `b254121d0c687c74ecc44384dcbb57e11af6735ffffe31ae51b2012f55ab9f6f` and reused 7,680 cached tokens | Verify all IDs, not just equal counts or a successful request |
| Normalized DSH 257K | 257,684 input passed in 108.26s; follow-up 257,738 input passed in 2.04s | Bounded cache probe supports fast continuation |
| Actual DSH near 1M | 1,007,688 input passed after 1,132.09s and three automatic timeout retries | Context acceptance succeeded; transport retries require separate correction/testing |

The V3 scheduler guards the *single chunked-prefill owner*, not all concurrency. Complete fitting short prefills remain admissible. It rejects changed upstream source hashes. The current scheduler file readback is `f87e90c04cf01f2a5cbf4921a0fd57b9b21bb65acfe5fceeceadecf076ad448e`.

## Transport and restart findings

The first successful actual DSH runs retried at the five-minute boundary. A delayed synthetic endpoint reproduced it despite one-hour DSH/provider settings. Installed Undici source supplies 300-second header/body defaults; a scoped dispatcher override makes the managed internal inference origin's waits one hour while preserving other origins and caller cancellation. The actual delayed-response retest returned the expected persisted answer after 316.59 seconds with zero retries. It consumed no GPU inference and is labelled as transport evidence.

The first profile-backup init also needed repeat-start handling. It now verifies an existing rollback copy rather than refusing or overwriting it. All 20 runtime replacements loaded the qualified transport source and preserved 40 workspace/attachment markers. Rollback retains this independent startup repair while removing the optional transport overlay. Actual session files and central mounts remain unchanged.

Completed synthetic candidates were removed after a new test pod hit CPU admission limits on the single node. Only named disposable pods were deleted; no user runtime, model or data volume was removed. The final managed canary was then admitted normally.

## Final request path

DSH authenticates normally and sends its model request to LiteLLM. Existing inference-only keys remain inside their runtimes. Canonical DeepSeek requests pass through an output-alias guard and a loopback-only proxy. Other model routes retain their previous configuration.

The loopback proxy normalizes backend defaults, calls the running SGLang tokenizer with messages/tool schemas/template options, and requires valid token IDs and a 1M model limit. Counting errors fail closed. It caps output at 8,192 and reserves 256 tokens. Unsupported shapes do not silently bypass counting; multimodal requests above 128K are rejected. Backend endpoints and request IDs are managed, not chosen by user text.

Requests above 128K acquire one process-shared lease. A two-second probe checks cached context. A cold miss is aborted by its owned request ID; the prefix is then extended in 2,048-token steps with yields between them. Reuse is checked after each extension. Temporary one-token completions are discarded and never executed or persisted as model answers. Cache loss, timeout or failed handoff stops the request rather than repeating a blocking monolithic prefill. Ordinary requests do not acquire the long lease.

The final request uses the same conditioning envelope whose IDs were prepared. Streaming handoff has a first-content deadline; cleanup closes connections, aborts only owned work and releases the lease. For non-streaming clients, the same guarded internal stream is assembled into JSON. The actual 140,018-token non-streaming test returned the exact answer in 44.99 seconds.

One gateway replica owns admission. Scaling replicas requires distributed ownership; independent locks would not enforce a shared long-request limit. The measured pool is 1,179,648 slots, so two full 1M contexts are not promised. The backend cap remains 16 for ordinary traffic.

## Acceptance and preserved data

The runtime image from Azure build 62773 is `dsoreg-sm1-p1.bot.or.th/da-gpu-server/dsh-runtime@sha256:87bc12dd5c2419e640c11358881f01709944a259498cf38a699fcc57d037e1a3`. Its startup and policy files match source checkpoint `e796655` / Azure `c20b310`. Later proxy/docs sources do not imply that a different runtime image is deployed.

The initial proxy/runtime checkpoint was GitHub `81717b4` / Azure `b5bcb3d`. The managed transport/restart repair is `621ae55` / `5f4d76f`; final probe/marker sources are `e3867bb` / `4f61bdd`. Immutable configuration and live source hashes bind the running proxy independently of the runtime-image build. The controlled rollout requires Recreate and one writer, preserves all volumes/mounts and backs up the original profile within each user's private PVC. Rollback restores that profile before the old image; existing user content is not overwritten.

Post-restart checks verified all mapped private login/logout paths, 16 denials of owner histories to other users, non-admin dashboard denial and visible fixed-schema audit. `thanatcc` still lists 80 histories; all 87 files captured immediately before this upgrade remained byte-identical. A workspace marker survived and was removed. Owner/admin actual terminal WebSockets executed as UID 10001 in both environments. No account ownership or DA_WORKSPACE path changed.

Automatic compaction uses ratio 0.875 and the plugin's pressure budget, normally 917,504 estimated tokens, with 65,536 headroom and 8,192 summary output. A disposable lower-threshold fixture exercised the actual automatic path: summary persisted, the verification code survived, recall succeeded and the end record had no error. This does not establish every historical session's recovery or a near-1M summary's fidelity.

## Performance interpretation

During the first near-1M run, two real DSH short calls finished in 4.03/6.04s. During the production follow-up, two finished in 4.03/4.04s. Concurrent API output during long work was 16.01 aggregate tokens/sec at two requests and 27.10 at four. Exact output matched and the model did not restart. These are bounded samples and output slows under long load.

The final managed mixed sample was slower: two actual DSH calls took 6.04/8.04s, and aggregate API output was 8.98 tokens/sec at two requests and 15.51 at four. The owned long test remained active before and after. These results are included alongside the earlier faster sample; throughput varies with long-prefill work.

The older 105-response stress test belongs to the 128K product baseline. Its 16-request throughput must not be represented as 16 concurrent 1M capability. Cold prefill latency, output decode rate, aggregate throughput and short-answer latency measure different things; a tiny eight-token long-context answer is not a useful sustained decode benchmark.

## Evidence and reproduction

- [Current DSH near-1M record](context-evidence/dsh-final-wire-near-1m-20261016.json)
- [Tokenizer IDs and cache proof](context-evidence/tool-default-exact-ids-and-cache-20261016.json)
- [Failed 500K trial](context-evidence/dsh-warmed-500k-20261016.json)
- [Real write/read tool acceptance](context-evidence/final-wire-tool-acceptance-20261016.json)
- [Non-streaming and endpoint rejection](context-evidence/final-wire-api-acceptance-20261016.json)
- [Automatic compaction fixture](context-evidence/dsh-automatic-compaction-fixture-20261016.json)
- [Production mixed traffic](context-evidence/production-1m-mixed-concurrency-20261016.json)
- [Owner/admin composed profiles](context-evidence/1m-composed-owner-admin-profiles-20261016.json)
- [Private access after rollout](context-evidence/1m-private-login-history-access-20261016.json)
- [Legacy persistence](context-evidence/1m-runtime-legacy-persistence-20261016.json)
- [Image content/source readback](context-evidence/runtime-1m-image-content-20261016.json)

Run probes only in the named disposable test pods, with fresh output filenames and stopped escalation on actual failures. A stress probe consumes the shared service. The detailed setup, rollback procedure, limits and current final results are in [the LLM guide](LLM_SETUP_AND_TEST_RESULTS.html). Prior failures are preserved; configuration, local tests, actual deployment and full user-facing behavior remain distinct evidence categories.
