# DSH — Real Repository Accuracy and Long-Output Test

## Result and operational meaning

**Completed real DSH execution; accurate targeted fact values; citation and narrative acceptance NOT passed.** The local DeepSeek service processed **992,638 input tokens** and produced **4,767 output tokens**, including a **2,252-word engineering review**. This is materially more useful than an eight-token sentinel, but the result also demonstrates why generated source citations need independent checking.

All **15 intended factual values** match the frozen sources after manual interpretation of equivalent units, Boolean wording and time formats. This is not the same as following the complete output contract. The unchanged automated exact-match checker found **7/15 literal value matches** and **4/15 answers satisfying every literal value, requested-source, supporting-line and quotation condition**. Unit-annotated correct answers such as `256 tokens` are counted differently by the literal checker; those are not factual errors. The separate manual review does not rewrite or turn the original exact-match result into a pass.

The generated narrative contains unsupported or inadequately cited conclusions. It is retained below for inspection, **not adopted as verified operational guidance**. This one task does not establish arbitrary million-token reasoning accuracy or a complete code/security audit.

## Actual path, sources and test method

The client was the **actual DSH agent** using its HTTP RPCs in a disposable current-image runtime, authenticated through its local launch-token exchange. The path was DSH → internal LiteLLM → final-wire guard → SGLang on the existing four-GPU model. This was not a manual browser-interface test, Claude Code run or TrueForge run. No code-execution tools were requested: the source material was supplied inline, while DSH's tool definitions still formed part of its model envelope.

The corpus contained **239 current source blocks and 99 labelled historical document revisions**, drawn from DSH `7f477341a5429c7dfe393dffe89f0cdef2887333` and GPU_server `81f42dc522f51e9e940ade181b78945984b189ce`. Identical complete files were deduplicated. Generated HTML/assets and raw synthetic test prompts were excluded. Recognized credential-shaped token/assignment patterns were redacted. The complete corpus stays in the retained local test artifacts; the pinned source specification and input hash allow reconstruction without adding the full corpus to Git.

Historical revisions deliberately overlap: this was a realistic implementation/change-history audit, not a million independent new facts. Reference source blocks occur near 1%, 31%, 62%, 87% and 92% of the prompt by character position; these are not exact tokenizer positions. The answer key was prepared before model output and was not included in the prompt. The model was asked for 15 source-backed values, exact quotations no longer than 200 characters, narrow citations, and a 1,400–1,800-word report using at least eight source blocks. Its actual 2,252-word report exceeded that requested range.

The submitted prompt SHA-256 is `ffbbb9b15242c42275f2e81d616385a51d22d2af4ee336e34cff9b81c659e738`. The retained prompt was reconstructed from pinned Git objects and matched this hash. DSH's saved conversation was read back and its user prompt matched the submitted content.

## Time, concurrency and memory

| Measurement | Actual recorded result |
|---|---|
| Input / output / total | 992,638 / 4,767 / 997,405 tokens |
| Complete DSH turn | **2,379.02 seconds — 39m39s**, including admission wait and retries |
| Before warming began | Approximately **1,065.25s — 17m45s**, including capacity wait, client retries, tokenization and other overhead |
| Exact-input prefix preparation | **1,163.40s — 19m23s**, 485 incremental steps |
| DSH-reported output phase | **147.524s** for 4,767 tokens; approximately **32.31 output tokens/s** in this one run |
| Short replies strictly overlapping admitted processing/generation | **18**, correct and persisted, **4.03–10.05s**, in pairs |
| Short replies during output generation itself | **2**, included in the 18 above |
| All short replies in the observation window | **36**; the other 18 occurred before admission and are not counted as admitted-load evidence |
| Post-long idle pair | **2.03s each**, correct and persisted; separate from the overlap count |
| DSH-side capacity retries | **3**; the successful attempt followed them |
| Model continuity | Same model pod/image, **zero restarts** |
| Admitted-phase shared-model log window | **1,356 recovering mapping-OOM warnings**; zero matches for checked fatal CUDA OOM, OutOfMemoryError, illegal-memory or scheduler-exception signatures |
| Minimum sampled GPU free memory | **12 MiB**; sampling does not establish the transient minimum |

Preparation is correlated to the forwarding lifecycle event by exact final input count and timing, not a globally unique request ID. Output-phase throughput is a bounded observation, not a sustained decode benchmark or SLA. The initial single short baseline took 4.07s; it is not a controlled two-request baseline, so no causal percentage slowdown is inferred.

## Setup failure, queue behavior and test-harness correction

The first setup attempt stopped after about 37 seconds when an oversized `kubectl exec` helper argument received **HTTP 414 from the control-plane ingress**. This was a test-helper transport failure, not a DSH inference answer. The helper is now uploaded as a file rather than passed in a large URI argument.

Deleting that disposable runtime did **not** establish upstream cancellation. The subsequent review observed a held long-admission slot, while shared warming continued. A lifecycle event consistent with the interrupted preparation reported 992,606 tokens and 1,157.851s. Because the logs lack a unique request binding, the report does not assert stronger ownership attribution than the timing/count correlation supports.

The subsequent fresh-prefix review received three capacity-busy 429s and retried through **DSH's own client policy**. This is distinct from the already-disabled LiteLLM Router rate-limit retries. When the slot was released, the current review was admitted and its new prefix was prepared. The earlier prefix-progress observations alone did not establish which request owned the slot; that interpretation was corrected during the run.

The harness now checks **both the actual admission lease and GPU running/queue metrics** before launching a future review. Warming yields can show zero GPU requests while the long lease is still held. A live nonblocking lease check and three regression tests verify that this state is rejected. Full end-to-end cancellation across DSH, LiteLLM and the guard remains a separate verification requirement; runtime deletion alone must not be presented as confirmed inference cancellation.

## Answer and citation results

| Check | Result and interpretation |
|---|---|
| Intended factual values, manual source check | **15/15 correct** after equivalent-unit/time interpretation |
| Literal value strings, original checker | **7/15**; this deliberately strict comparison penalizes unit annotations |
| All strict answer conditions together | **4/15**; retained as failed, not silently relaxed |
| Answer quotations literally within cited lines | **14/15**; Q11 changes the source text |
| Answer quotations within requested 200-character limit | **10/15**; Q08, Q11, Q12, Q13 and Q15 exceed it |
| Requested source and reference definition-line selection | **13/15**; Q04 omits the numeric definition, Q13 uses a different current file |
| Narrative citation ranges pointing to existing source lines | **69/69** |
| Narrative ranges within requested maximum of 12 lines | **57/69**; 12 are broader |
| Narrative support | **Not fully accepted**; valid line locations do not establish that every attached claim is supported |

The one non-verbatim quotation is Q11: it changes `for (const model of aliases)` to `for model of aliases)`. Its reported value `0.875` is correct, but the purported quotation is not. Q04 cites the condition using `LONG_THRESHOLD` without its numeric definition; Q13 gives the right recorded duration from a different current guide instead of the requested README and uses `19m34s` rather than `19:34`.

### Original exact-match answer table

This table preserves the model values and original checker outcomes. A `No` does not automatically mean the intended factual value is wrong; the separate categories above explain the failures.

| Question | Original model value | Reference value | All strict conditions met? |
|---|---|---|---|
| Q01 | 1048576 | 1048576 | Yes |
| Q02 | 8192 | 8192 | Yes |
| Q03 | 256 tokens | 256 | No |
| Q04 | count + data['max_tokens'] > LONG_THRESHOLD (131072) | 131072 | No |
| Q05 | 300 seconds | 300 | No |
| Q06 | 2048 token IDs (WARM_STEP = 2048) | 2048 | No |
| Q07 | 2 seconds | 2 | No |
| Q08 | false (strict: false) | false | No |
| Q09 | False | false | Yes |
| Q10 | 15 seconds | 15 | No |
| Q11 | 0.875 | 0.875 | No |
| Q12 | 65536 | 65536 | No |
| Q13 | 19m34s | 19:34 | No |
| Q14 | sandbox_da_agent_public_data | sandbox_da_agent_public_data | Yes |
| Q15 | rejected | rejected | No |

### Source-review findings in the generated narrative

| Finding | Problem | Required correction |
|---|---|---|
| N1 | The generated statement that no approved corporate SLA exists goes beyond the supplied evidence. | No approved SLA was supplied or established by this review; absence in the corpus is not proof of nonexistence. |
| N2 | The report calls the shared model the only shared writable-adjacent resource. That exclusivity is unsupported. | Describe specific isolation boundaries; the architecture also includes shared gateway, audit and central-storage infrastructure. |
| N3 | S0273:L1 is a test-file comment, not the asserted exactly-one-identity-header check. | Cite the actual assertions, not a comment as proof of a test result. |
| N4 | The 512Gi container memory claim cites S0280:L87-L98, which contains model arguments, not the memory resource limit. | The resource limit is at L137; distinguish host/container RAM from GPU attention workspace. |
| N5 | The reconciliation says one-long admission was unchanged from the 128K checkpoint. S0002:L7 instead says product admission remained to be implemented. | The current one-long admission policy is verified in current source; do not project it backwards into that checkpoint. |
| N6 | A single NetworkPolicy excerpt is treated as proof that every other egress path is denied. | Effective Kubernetes egress is the union of applicable policies; configuration excerpts alone do not establish the deployed complete boundary. |
| N7 | The execution description leans on bootstrap shared-pool defaults without explaining the current per-user target mapping. | Use getEnvironmentTarget and the configured per-user mapping to explain private routing; distinguish bootstrap templates from deployed topology. |

These findings are a Codex source-based assessment, not DeepSeek grading itself or a human assessor sign-off. The original response is not patched to hide them. The predeclared narrative rubric records four criteria met, three partially met and one not met; no calibrated general accuracy percentage is inferred from that rubric.

## Persistence, cleanup and reproducibility

The disposable runtime mounted no user workspace/history PVCs. Its **78 session files** were archived, downloaded, hash-verified and independently listed inside the archive. Archive SHA-256: `ddb3f0415f6c5b7ef9656a64ec6e15aa2b4bd6e52ed6732a3301c3d2240dca47`. The archive and full prompt remain local test artifacts, outside Git.

The test pod was deleted and its absence verified. The long-admission lock was free afterward, and an authenticated ordinary inference call returned the exact expected answer in **0.25s**. The shared model pod/image and zero restart count were unchanged. No Production inference configuration was modified for this test.

To reconstruct the exact corpus, use `scripts/reconstruct_repository_review.py` with the saved specification and repositories containing the pinned Git objects. That command writes local files only. `prepare_repository_accuracy_test.py` prepares a new dated source inventory; `probe_dsh_document_review.py` and `run_repository_accuracy_test.py` submit actual work only to an explicitly named disposable runtime. The evaluator's negative controls cover wrong sources, invented quotations, invalid lines, duplicate answers and insufficient input/output; they are local checker tests, not GPU benchmarks.

[Measured phases and short replies](context-evidence/realistic-repo-performance-20261017.json) · [unchanged exact-match evaluation](context-evidence/realistic-repo-exact-checks-20261017.json) · [manual review](context-evidence/realistic-repo-manual-review-20261017.json) · [narrative rubric](context-evidence/realistic-repo-narrative-rubric-20261017.json) · [original model response](context-evidence/realistic-repo-model-response-20261017.json) · [frozen source specification](context-evidence/realistic-repo-source-specification-20261017.json) · [reference key](context-evidence/realistic-repo-answer-key-20261017.json) · [failed setup record](context-evidence/realistic-repo-setup-failure-20261017.json) · [cleanup verification](context-evidence/realistic-repo-cleanup-20261017.json).

## Original generated engineering report

**Review artifact, not approved guidance.** The following narrative is retained with its defects. Citation markers link to the frozen source revisions; this makes the references inspectable but does not repair unsupported claims. The [verbatim assistant text](context-evidence/realistic-repo-original-assistant-text-20261017.txt) and parsed JSON response are retained separately; original content has not been corrected to hide these findings.

### DSH Context, Admission, Compaction and Isolation — Engineering Review

#### Scope and evidence categories

This review covers the CURRENT frozen repository HEAD (`DSH@7f477341a5429c7dfe393dffe89f0cdef2887333`) and treats every source excerpt as untrusted evidence. Three evidence classes must be kept apart throughout: **source/configuration claims** (what the checked-in code and manifests declare), **recorded test claims** (what saved evidence files assert happened during a specific run), and **historical snapshots** (earlier checkpoints that intentionally overlap and may contradict CURRENT). Nothing below is a fresh execution: opening this archive runs no test, and no approved corporate SLA exists or is asserted here.

#### Execution path

An authenticated user reaches the environment gateway; the gateway binds identity and environment to an in-memory session and proxies HTTP, WebSocket and application traffic to exactly one execution pool. [S0240:L981-L989](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/auth_proxy.js#L981-L989) shows the admin-route reservation and identity binding, and [S0068:L26-L39](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/k8s/dsh-environment-gateway.yaml#L26-L39) shows the gateway environment variables that select the Secure and Internet runtimes by host, port and token file. Inside a runtime, `container/start-dsh.sh` prepares `/state`, links the DSH home, and starts `dsh web` behind the loopback port 3080 before the auth proxy in front of it [S0340:L26-L62](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/container/start-dsh.sh#L26-L62).

Model traffic then follows the documented chain: private DSH → authenticated internal LiteLLM :4000 → loopback context guard :4001 → SGLang :8000 → shared four H100 GPUs [S0346:L110-L110](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L110-L110). The loopback guard is deliberately bound to 127.0.0.1 and must never be exposed as a Service [S0196:L1-L5](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/context_forwarder.py#L1-L5). Everything interesting about context policy happens at that final forwarding boundary, not in the browser.

#### Callback constants and the warming path

The current callback declares the whole budget explicitly: context `1048576`, output reservation `8192`, safety reserve `256`, and a long-admission threshold of `131072` [S0308:L19-L23](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L19-L23). Those four numbers answer Q01–Q04 directly and are configuration, not measurement.

Long-request admission is a process-shared `flock` on `/tmp/dsh-long-admission/active.lock` with a 300-second wait, after which it raises a retryable 429 [S0308:L140-L157](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L140-L157). Ordinary requests never touch that lease because the lease is only acquired when `count + max_tokens` exceeds the long threshold [S0308:L198-L201](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L198-L201) — this is the code-level basis for the "ordinary requests remain concurrent" claim, and it is also why a single gateway replica is required: independent replicas would each own a separate lock file and would not enforce one shared long-request slot [S0289:L50-L50](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/END_TO_END_1M_ROLLOUT_20261016.md#L50-L50).

Prefix preparation has two modes. A bounded cache probe of two seconds is attempted first; on a cold miss its own request is aborted by request ID. Otherwise the prefix is extended in 2048-token steps, with reuse checked after every step and a hard failure if the previous prefix was evicted [S0308:L26-L27](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L26-L27)[S0308:L104-L138](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/long_context_callbacks.py#L104-L138). Intermediate one-token completions are discarded and never become tool actions or conversation messages [S0289:L46-L46](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/END_TO_END_1M_ROLLOUT_20261016.md#L46-L46). This is the mechanism behind the honest statement that a hot continuation can return in about two seconds while cold input throughput is a different quantity altogether [S0346:L150-L151](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L150-L151).

#### The warming/default mismatch and its correction

The most instructive defect in this archive is a prompt mismatch that was initially mistaken for insufficient warming. An earlier tool request counted 7,689 tokens while inference processed 7,561 [S0346:L130-L130](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L130-L130). The cause was that the backend tokenizer materialized an omitted `strict` default for function schemas differently from the chat inference path, so warming the counted token sequence could not guarantee a reusable prefix for the actually forwarded sequence.

The CURRENT normalization closes that gap by materializing prompt-affecting defaults explicitly: `continue_final_message` defaults to `False`, and a function whose `strict` is `None` is set to `False` [S0272:L4-L12](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/context_envelope.py#L4-L12). The loopback proxy applies that normalization to the final wire payload and then counts that same conditioning envelope, including messages, tools, tool choice, reasoning effort and template options [S0196:L85-L89](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/context_forwarder.py#L85-L89). Forwarder regression tests now assert that counted conditioning equals forwarded conditioning, that the exact returned IDs reach warming, and that explicit caller values are preserved [S0279:L140-L173](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/tests/test_context_forwarder.py#L140-L173). A fresh alignment check recorded identical prompt token IDs for a 258-token synthetic tool-schema request [S0346:L134-L134](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L134-L134) — a recorded test claim, not a re-derivation.

#### Long-request admission versus ordinary concurrency

The honest reading of the CURRENT material is that admission and concurrency are two different budgets. One request above 128K is admitted at a time; ordinary requests bypass the lease and stay concurrent, though they can still queue and slow down [S0346:L119-L120](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L119-L120). The measured cache pool of 1,179,648 token slots is explicitly described as supporting one near-1M request plus smaller work, **not** two complete 1M contexts [S0346:L123-L123](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L123-L123), and the qualified operating boundary excludes two full simultaneous 1M requests and sustained-load guarantees [S0346:L50-L50](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L50-L50).

A recorded live test of the admission boundary used a deliberately held lock rather than a fabricated GPU workload, producing a real authenticated 429 after 300.36 seconds while ordinary DSH replies continued, followed by successful lease release and a 400 for oversized input [S0346:L24-L26](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L24-L26)[S0346:L102-L102](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L102-L102). The same material records that the first real 1M attempt exposed a genuine queueing defect: LiteLLM's default Router retried rate-limit responses twice and the client timed out, which was corrected by setting `RateLimitErrorRetries: 0` for only the two guarded aliases [S0346:L28-L30](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L28-L30). The promotion script enforces that narrowness by refusing to proceed if the guarded model groups change [S0304:L19-L28](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/promote_1m_proxy.py#L19-L28).

#### Cold versus cached latency

Recorded DSH results separate cold prefill cost from hot-prefix cost in a way that resists optimistic summarization. The current recorded cold near-1M request returned an exact persisted reply for 1,007,689 input tokens in 1,173.92 seconds, and the follow-up write/read tool continuation at 1,008,103 input tokens completed in 20.16 seconds [S0346:L19-L22](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L19-L22). Eighteen ordinary DSH replies overlapped the cold run at 4.03–12.04 seconds, and the slowest of those exceeds the earlier sub-five-second small-probe target [S0346:L23-L23](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L23-L23)[S0346:L86-L86](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L86-L86). Under long load, short replies took 0.477–0.613 seconds at 120,049 input tokens in one bounded sample [S0346:L46-L46](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L46-L46).

Memory margin is recorded as thin: 1,132 recovering allocator mapping warnings with a minimum warning-reported free memory of 1.75 MiB in the current-image progressive test window, with no checked fatal CUDA/OOM or scheduler-exception signatures [S0346:L48-L48](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L48-L48). Earlier qualification evidence for the preceding image recorded 1,460 such warnings and a 9.75 MiB minimum [S0346:L11-L11](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L11-L11). These are recorded observations, not headroom guarantees, and they are the strongest reason not to extrapolate from a passing near-1M text case to general capacity.

#### Compaction

The CURRENT 1M runtime policy is configured through `configure_runtime_context.js`, which sets both aliases to the requested context, caps `maxTokens` at 8192, and installs per-model compaction policies with `thresholdRatio: 0.875` and `headroomTokens: 65536` for the 1M case [S0005:L12-L33](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/configure_runtime_context.js#L12-L33). The documented formula yields `min(1048576 × 0.875, 1048576 − 8192 − 65536) = 917,504` estimated tokens [S0346:L195-L199](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L195-L199).

Two qualifications matter. First, compaction pressure is estimated, unlike the proxy's exact tokenizer count, and a large single tool result or attachment may reach the request guard before automatic compaction runs; overflow is then refused [S0346:L201-L201](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L201-L201). Second, a code/configuration calculation is not proof of successful compaction: a lowered-threshold fixture exercised the real plugin path and verified summary persistence plus recall of a verification code, but that does not certify every historical session [S0346:L158-L158](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L158-L158). Under the earlier 128K configuration the installed plugin's arithmetic produced a 57,344-token threshold rather than the widely repeated ~98,304 figure, because output reservation and headroom are subtracted [S0058:L55-L59](https://github.com/skunpoj/dsh_setup/blob/2c206b52fe7bed07f246fbe6a7dfd8ae98ef5c99/docs/LLM_SETUP_AND_TEST_RESULTS.md#L55-L59) — a useful illustration of why historical prose about "75% of 128K" must not be carried into the 1M configuration.

#### Memory tradeoffs

The 1M budget was reached by trading allocation shape, not by adding memory. A static memory fraction of 0.92 produced a large apparent KV-slot count and then failed a real ~262K request with CUDA OOM during sparse-attention scoring; lowering the static fraction to 0.88 failed before inference because the cache layout could not initialize [S0219:L18-L19](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/CONTEXT_OPTIMIZATION_20261015.md#L18-L19). The tested balance was static 0.90 with progressively smaller prefill chunks (4,096 → 2,048 → 1,024) and maximum prefill tokens reduced to 2,048 [S0219:L42-L43](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/CONTEXT_OPTIMIZATION_20261015.md#L42-L43). The current manifest carries those settings, along with a 512Gi memory limit and 1M context length [S0280:L87-L98](https://azuredevops.bot.or.th/BOTCollection/da_Team_DA_Board/_git/GPU_server?path=%2Fdeployment%2Fvllm%2F04-vllm-deepseek-v4-1-flash.yaml&version=GC81f42dc522f51e9e940ade181b78945984b189ce&line=87&lineEnd=99&_a=contents).

The KV-slot count is explicitly *not* an executable-capacity measure: temporary attention workspace, kernel loading and allocator behavior also consume GPU memory, and the older 2,185,984-slot observation did not establish that two 1M requests could run [S0219:L41-L41](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/CONTEXT_OPTIMIZATION_20261015.md#L41-L41). Long context therefore remains an exceptional workload rather than a routine concurrency target [S0219:L37-L37](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/CONTEXT_OPTIMIZATION_20261015.md#L37-L37).

#### Isolation, history and storage claims

Execution isolation contributes to the same budget conversation because the shared model is the only shared writable-adjacent resource. The gateway canonicalizes identity for both HTTP and raw WebSocket carriers so that forged or mixed-case `x-dsh-user` headers cannot reach an application [S0240:L288-L302](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/auth_proxy.js#L288-L302), and a regression test asserts exactly-one canonical identity header across default and custom routes [S0273:L1-L1](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/tests/test_proxy_identity_headers.js#L1-L1). The egress policy allows only the internal LiteLLM pod on TCP 4000, the internal resolver on 5353, specific KDC addresses on 88 and one Livy endpoint on 28998, with everything else denied for offline-labelled pods [S0286:L1-L53](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/k8s/dsh-egress-policies.yaml#L1-L53). That is restricted egress, not an air gap, and the material repeatedly refuses to claim exhaustive leakage coverage [S0346:L217-L217](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L217-L217).

Legacy history handling is documented as header-only migration: only the compressed first-frame `cwd` changes, conversation event frames must remain byte-identical by SHA-256, and unmapped or colliding destinations cause refusal before mutation [S0256:L1-L1](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/session_cwd_migration.py#L1-L1)[S0256:L77-L85](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/session_cwd_migration.py#L77-L85). The recorded aggregate for the 80 histories in 82 files is retained across process replacements [S0087:L53-L53](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/README.md#L53-L53).

#### Limitations of prior tests

Several claims in this archive are recorded tests with bounded scope, and the source says so. Percentiles from small samples are "not an SLA" [S0346:L169-L169](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L169-L169). The 105/105 exact-reply campaigns cover short bursts and approximately 24K/96K/120K mixed input, and the retained review explicitly warns that separate runs must not be added together as one uninterrupted benchmark [S0346:L56-L56](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L56-L56)[S0346:L93-L93](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L93-L93). The 16-concurrency burst level is a tested level for short outputs, not a promise of sixteen large contexts [S0205:L39-L39](https://github.com/skunpoj/dsh_setup/blob/33406ddc7033a3cf60f7d90fd1578ee1b9bc0289/docs/LLM_SETUP_AND_TEST_RESULTS.md#L39-L39). The delayed-response transport fixture is transport evidence that uses no model inference, not a quality benchmark [S0346:L187-L187](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L187-L187). Remaining coverage limits include no sustained soak, no two concurrent full 1M requests, no near-1M vision, no full 8,192-token generation near maximum input and no arbitrary million-token semantic-quality assessment [S0346:L106-L106](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L106-L106).

#### Reconciling historical 128K statements with CURRENT

The archive contains many historical statements that DSH and LiteLLM enforce a 131,072-token total budget, an 8,192 output ceiling, a 256-token buffer and compaction around 98,304 [S0002:L7-L7](https://github.com/skunpoj/dsh_setup/blob/242b7f7cc02c4a5b8b23423e96b0c7a8f000435e/docs/UPSTREAM_SYNC_AND_INTERNET_POLICY.md#L7-L7). Those are accurate descriptions of the earlier product baseline and are preserved as dated checkpoints, not as CURRENT behavior. CURRENT source sets the aliases to 1,048,576 total context with an 8,192 output cap [S0005:L12-L17](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/configure_runtime_context.js#L12-L17), and the CURRENT README describes the same reacceptance path [S0087:L79-L81](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/README.md#L79-L81). The honest reconciliation is therefore that the *old guardrail number is superseded*, while the *output ceiling, proxy reserve and one-long-request-at-a-time admission are unchanged*. No new test result is introduced by that reconciliation.

Two further historical figures deserve the same treatment. The 128K-era 57,344-token compaction calculation is arithmetic on the old context, not a CURRENT threshold [S0058:L55-L59](https://github.com/skunpoj/dsh_setup/blob/2c206b52fe7bed07f246fbe6a7dfd8ae98ef5c99/docs/LLM_SETUP_AND_TEST_RESULTS.md#L55-L59). The historical near-1M backend successes belong to an earlier scheduler profile and are not fresh proof of current-profile near-1M behavior [S0237:L42-L42](https://github.com/skunpoj/dsh_setup/blob/4d7cc342bf7660158925dc8b1bad0d1da5b11944/docs/LIVE_REVIEW_AND_PERFORMANCE_20261016.md#L42-L42).

#### Practical operational workflow

1. **Read the running facts, not the prose.** Read back image digests, mounted ConfigMaps and effective profiles before acting; portal scripts exist for this and explicitly avoid exporting secrets [S0234:L17-L31](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/review_live_status.py#L17-L31)[S0234:L58-L79](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/review_live_status.py#L58-L79). Repeatedly, the source warns that a saved manifest is not evidence of live state.
2. **Keep one writer per state directory.** Runtime replacement uses Recreate with a single replica, and the gateway likewise runs one replica so that admission ownership is genuine [S0289:L50-L50](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/END_TO_END_1M_ROLLOUT_20261016.md#L50-L50)[S0302:L100-L112](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/rollout_runtime_hardening.py#L100-L112).
3. **Gate long-context changes on evidence that matches the change.** The proxy promotion script refuses to apply without a passed near-1M acceptance whose recorded usage exceeds one million input tokens and whose model pod is unchanged [S0304:L140-L147](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/promote_1m_proxy.py#L140-L147).
4. **Preserve the rollback pair.** Context promotion backs up the previous profile inside each private PVC before the image changes, and restores that profile before starting the old image [S0010:L1-L5](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/promote_1m_runtimes.py#L1-L5)[S0010:L26-L44](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/scripts/promote_1m_runtimes.py#L26-L44).
5. **Do not overwrite newer data during rollback.** The current material states repeatedly that rollback does not overwrite newer workspace or history writes [S0346:L217-L217](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L217-L217).
6. **Treat warning-heavy success as provisional.** Recovering allocator warnings with single-digit-megabyte reported headroom accompany passing tests and are recorded as material limitations rather than smoothed away [S0346:L11-L11](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/docs/LLM_SETUP_AND_TEST_RESULTS.md#L11-L11).
7. **Keep the transport fix scoped.** The dispatcher override supplies one-hour header and body waits only for the operator-managed internal inference origin, leaving other origins and caller abort signals untouched [S0357:L6-L13](https://github.com/skunpoj/dsh_setup/blob/7f477341a5429c7dfe393dffe89f0cdef2887333/tests/test_managed_inference_transport.js#L6-L13).

#### Bottom line

CURRENT source declares a 1,048,576-token context with an 8,192 output ceiling and a 256-token reserve, one long request above 128K admitted at a time behind a 300-second bounded 429, 2,048-token incremental prefix warming with a two-second cache probe, explicit normalization of `continue_final_message: false` and `strict: false`, a 15-second first-output handoff deadline, 0.875 compaction ratio with 65,536 headroom, and rejection of above-128K multimodal image input. The recorded evidence supports near-1M *text* cases with tool schemas and a write/read continuation, at thin memory margin, and does not support an approved SLA, two-full-1M acceptance, or any claim that prior 128K-era measurements describe the current configuration. Every benchmark-shaped statement above is either a source claim or a bounded recorded claim; none is a fresh test performed by this review.
