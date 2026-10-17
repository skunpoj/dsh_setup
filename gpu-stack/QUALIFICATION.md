# Publication qualification

The sanitized bundle passed 31 Linux unit/structural tests on 17 October 2026, with no skips. The same Windows suite passed with three POSIX file-lock tests skipped; those three were included in the Linux run. Tests cover final-payload/tool-default consistency, cancellation and lease cleanup, foreground scheduling, cache-loss refusal, output/total budgets, unsupported-route rejection, immutable image/name validation, Secret references, loopback-only forwarding, policy structure and content/source hash checks.

A separate pre-publication scan checked the new bundle against known private domains, node/user/share names, private addresses and credential markers before it entered the public checkout. Only generic Kubernetes Service names, public upstream image references and public software/model identifiers remain. Source and publication hashes are in `SOURCE_MANIFEST.json`. New bundle qualification does not redact earlier repository history.

The initial publication checks were source/template qualification; they did not perform GPU startup, model-weight integrity, database restore, network enforcement or near-1M inference. Existing long-context/performance measurements belong to the recorded deployment and are described separately. The template requires operator-supplied model storage, database, protected Secrets, matching DNS/network policy and client qualification before use. Publishing it does not alter Production.

Hosted CI activation remains pending: the publishing credential lacks workflow-write permission. The reviewed workflow is provided as `ci-example.yml`; the 31-test Linux result above was run directly, not by GitHub Actions.

## Subsequent existing-node model acceptance

The later fresh-model test used the same pinned image, scheduler behavior and context/memory/concurrency profile, adapting the existing namespace/service labels, weight snapshot path/PVC, node selector and served aliases. Cold near-1M DSH capacity, bounded concurrent replies and current tool/output-budget behavior were exercised. An overlapping gateway reload caused retries in one completed tool continuation, and two ancillary retained-history trials were cancelled; those are not hidden or certified as passed. See the [measured report](../docs/FRESH_GPU_ACCEPTANCE_20261017.html). This does not qualify a wholly new cluster/database/network/storage deployment.

The reviewed current timing/foreground source and updated template passed **36 Linux tests with zero skips**. The Windows run passed with three POSIX lock cases skipped; Linux exercised those cases. A Windows temporary-path escaping issue in the test fixture was corrected using platform-safe paths. Source drift remains fail-closed.
