# Publication qualification

At initial publication, the sanitized bundle passed 31 Linux unit/structural tests on 17 October 2026, with no skips. The same Windows suite passed with three POSIX file-lock tests skipped; those three were included in the Linux run. Tests cover final-payload/tool-default consistency, cancellation and lease cleanup, foreground scheduling, cache-loss refusal, output/total budgets, unsupported-route rejection, immutable image/name validation, Secret references, loopback-only forwarding, policy structure and content/source hash checks.

A separate pre-publication scan checked the new bundle against known private domains, node/user/share names, private addresses and credential markers before it entered the public checkout. Only generic Kubernetes Service names, public upstream image references and public software/model identifiers remain. Source and publication hashes are in `SOURCE_MANIFEST.json`. New bundle qualification does not redact earlier repository history.

The initial publication checks were source/template qualification; they did not perform GPU startup, model-weight integrity, database restore, network enforcement or near-1M inference. Existing long-context/performance measurements belong to the recorded deployment and are described separately. The template requires operator-supplied model storage, database, protected Secrets, matching DNS/network policy and client qualification before use. Publishing it does not alter Production.

Hosted CI activation remains pending: the publishing credential lacks workflow-write permission. The reviewed workflow is provided as `ci-example.yml`; the 31-test Linux result above was run directly, not by GitHub Actions.

## Subsequent existing-node model acceptance

The later fresh-model test used the same pinned image, scheduler behavior and context/memory/concurrency profile, adapting the existing namespace/service labels, weight snapshot path/PVC, node selector and served aliases. Cold near-1M DSH capacity, bounded concurrent replies and current tool/output-budget behavior were exercised. An overlapping gateway reload caused retries in one completed tool continuation, and two ancillary retained-history trials were cancelled; those are not hidden or certified as passed. See the [measured report](../docs/FRESH_GPU_ACCEPTANCE_20261017.html). This does not qualify a wholly new cluster/database/network/storage deployment.

The earlier timing/foreground source and its updated template passed **36 Linux tests with zero skips**. The Windows run passed with three POSIX lock cases skipped; Linux exercised those cases. A Windows temporary-path escaping issue in the test fixture was corrected using platform-safe paths. Source drift remains fail-closed.

## Allocator correction and bounded prefill acceptance

The latest publication passed **45 portable Linux tests without skips**, including final-payload counting, cancellation, safe numeric diagnostics, cache-loss refusal, immutable references and the structural prefill/memory controls. The canonical forwarder/guard suite passed 37 Linux tests; it overlaps the portable cases. The model template fixes context 1,048,576, static memory 0.90, running cap 16, chunk 512, prefill budget 1,024, eight prefix tails, prefill batch cap two and separate prefill/decode. Publication hashes are refreshed after the documentation update.

The full actual DSH near1M plus concurrent-short result and preceding failures are recorded in the [allocator qualification](../docs/GPU_ALLOCATOR_QUALIFICATION_20261017.html). A successful focused 256K test did not qualify the failed mixed-batch near1M candidate; the final full retest was required.

## Preparation-step diagnostics and rejected speed trials

On 18 October 2026, the canonical forwarding/guard suite passed **39 Linux tests** and the portable bundle passed **47 Linux tests**, both without skips. The suites overlap. Added checks exercise bounded operator preparation-step configuration, cache-extension correctness, foreground yielding and numeric-only progress diagnostics. The operating default is 2,048 tokens. An 8,192-token trial did not qualify near-1M cache retention, and the faster DSpark candidate failed long-input memory allocation; neither is the default model profile. Source and publication hashes are refreshed after the final documentation changes. See the [actual DSH trial report](../docs/PERFORMANCE_OPTIMIZATION_20261018.html).


## DSpark score, FP4 and graph-memory qualification — 19 October

| Setting | Qualified value |
|---|---|
| Total context | 1,048,576 tokens across main DSH, LiteLLM and SGLang |
| Model / GPUs | DeepSeek-V4.1-Flash, tensor parallel 4, existing node |
| Recorded GPU memory | Four H100 NVL devices reporting 95,830 MiB each |
| Speculative decoding | DSpark, block size 5 |
| Static memory | 0.923 |
| Active requests / CUDA graph cap | 8 / 8 |
| Prefill chunk / batch budget | 1,024 / 1,024 tokens; two prefill requests; separate prefill/decode |
| Prefix tails / decode interval | 16 / 4 |
| Full / sliding-window cache slots | 1,150,976 / 17,920 |
| Attention-score temporary tile | 256 MiB |
| Preparation step | 2,048 tokens at the final forwarding boundary |
| Long admission | One active request above 128K; one FIFO waiter, at most 1,500s; further long requests receive 429 |
| Output budget | At most 8,192 tokens plus a 256-token safety reserve |

The canonical Linux suite passed **57 tests** and the portable suite passed **67 tests**, with no skips. They overlap. GPU startup checks passed 80 original-score cases, eight tiled cases, 132 FP4 cases and eight memory comparisons. Optimized Python modes are rejected before optional imports; normal-mode generated runtime bytes match the qualified hashes. Actual existing-node DSH results are recorded in the [performance report](../docs/PERFORMANCE_OPTIMIZATION_20261018.html). This qualifies the tested runtime on the existing node, not an untested fresh-cluster rollout.
