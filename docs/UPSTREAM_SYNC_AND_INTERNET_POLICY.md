# DSH upstream maintenance and release policy

## Why this is not a fully synchronized source fork

`dsh_setup` packages the official npm distribution and maintains deployment, authentication, routing, storage and model-configuration overlays. It does not copy the official monorepo. Updating the official package and preserving these overlays is the correct synchronization operation; merging all official source files into this deployment repository would mix two different repository purposes.

Fresh checks on 16 October 2026 found:

| Item | Observed value |
|---|---|
| Running DSH package and Dockerfile pin | `0.2.0-rc.2` |
| npm latest / next | `0.2.0-rc.2` / `0.2.0-rc.2` |
| npm alpha | `0.2.1-alpha.4` |
| Official master at 12:26 UTC | `1517a4dbca0a2789ff1d41ba439600f8547d23fa` |

The installed package therefore matches the default published release channel. Official master advanced during this work while npm latest stayed unchanged. The source HEAD and published package release are separate facts; the package metadata does not provide a `gitHead` mapping. The older comparison is superseded by [the fresh channel check](context-evidence/upstream-check-comprehensive-20261016.json). Explicit preview detection is recorded separately; the preview has not been built or deployed by that metadata check.

Upstream describes DSH as developer-preview software with breaking changes. See the [official README](https://github.com/deepseek-ai/deepseek-harness/tree/86a402200d95fecef4529d969836f1fe13c6cb0d#developer-preview) and [safety guidance](https://github.com/deepseek-ai/deepseek-harness/blob/86a402200d95fecef4529d969836f1fe13c6cb0d/SAFETY.md).

## Automated checking and candidate patching

The expanded `.github/workflows/upstream-candidate.yml` and its [tracked reference](UPSTREAM_CANDIDATE_WORKFLOW.yml) define:

1. Daily release checks at 02:17 UTC (09:17 ICT), manual dispatch, and checks on relevant source pushes/pull requests.
2. Tracking npm latest by default. A manual `candidate_version` can explicitly select a preview.
3. A Docker candidate build even when npm latest is unchanged, so the baseline is exercised too. Pull requests qualify their Dockerfile pin rather than silently testing another npm channel.
4. Pre-patch SHA-256 contracts for all ten upstream files our configurator mutates. The reviewed baseline hashes were derived from official npm package archives after SHA-512 integrity verification. Changed/missing targets stop the build; the automation never updates those hashes for itself.
5. Actual installed-module syntax/budget/profile checks, disposable DSH web startup and session/model-catalog RPC, anonymous/Host denial, gateway routing and forged-header tests, package promotion, Python rollback/manifests tests, and browser admin-dashboard checks. The actual runtime smoke test has no network or Production storage. The test directory is now included in the Docker context; its earlier exclusion was incompatible with the Dockerfile's test copy.
6. A package-pin branch and PR only after qualification succeeds. Existing branches/PRs are retained rather than overwritten. The write-capable proposal job is separate from the read-only candidate execution job.
7. Thirty-day build, package, test, image-ID and browser evidence artifacts plus a workflow summary. Failure blocks the proposal and is visible as a failed Actions run; no external notification service is configured.
8. No auto-merge, registry image publication or Production deployment in this GitHub workflow.

**Publication status before the comprehensive publication attempt:** the earlier Git push was rejected because its stored PAT lacked workflow permission. The expanded implementation has now passed local workflow linting and the baseline checks below. Publication and a completed hosted run must be recorded separately; a local YAML file is not an active schedule. No token value belongs in this document or chat.

The workflow requires GitHub Actions to be enabled and the repository setting allowing Actions to create pull requests. Hosted execution/PR permissions are separate from local tests. A no-update run still qualifies the baseline but skips PR creation. Scheduling occurs from GitHub's default branch; the Azure reference is not another scheduler. A bot-created PR may require approval before additional PR-event workflows run; qualification occurs before creation and does not rely on that event. See [GitHub trigger rules](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).

### Verification completed during implementation

- Official channel lookup validates the exact package name, version and SHA-512 integrity field; wrong package/version and missing integrity are refused by tests.
- The patch-contract check accepts a reviewed fixture and refuses changed or absent targets. It protects the ten known mutation targets; it is not a semantic audit of every upstream dependency.
- Workflow syntax passed checksum-verified official actionlint 1.7.12. Local gateway/routing/identity/catalog/contract tests and the admin browser test passed. Windows skips POSIX-specific cases; the hosted Linux job is responsible for those cases.
- An isolated Kubernetes pod ran the current pinned baseline image with no service-account token, credentials, durable mounts or network access. Actual installed-module checks, disposable web startup, authenticated session/model-catalog RPC, anonymous denial and untrusted-Host denial passed. This proves the new probe against the installed baseline, not a fresh Docker build of these new source changes. [Exact baseline result](context-evidence/upstream-baseline-runtime-20261016.json).
- Initial probe attempts used Bearer authentication instead of the web launch-cookie handshake, then sent an unnecessary argument to the zero-argument catalog method. They failed, were corrected, and are not counted as product regressions or successful acceptance. A subsequent temporary-pod creation collided with a terminating test pod; the corrected retry used a unique name. Temporary test resources were removed.

To reproduce detection locally:

```powershell
python scripts/check_upstream.py --output upstream-check.json
python scripts/check_upstream.py --candidate 0.2.1-alpha.4 --output preview-check.json
```

`--prepare-candidate` changes only the Dockerfile pin. Neither command installs packages into Production. Candidate version input is validated before registry lookup/preparation. Detection does not claim that text patches rebase themselves correctly.

## Why Production upgrades remain gated

Our compatibility layer still modifies selected package files. All ten current mutation targets now have pre-patch source contracts, but those hashes and candidate checks do not cover every future upstream semantic change. A changed target requires reviewing the source diff, adapting the overlay/tests and explicitly updating the reviewed contract. Prefer supported configuration/plugins over text patching as extension points become available; that migration is not complete.

Before deployment, qualify copied-state session reads, new prompts, compaction, attachments, tools, browser Host/Origin handling, HTTP/WebSocket terminal/application proxy, private-user/network boundaries and restart/restore. Review any unmatched patch target. Retain a compatible old image/configuration and coherent state recovery baseline. Read back the actual running image and test the affected behavior after cutover.

A passing build is a candidate result, not migration or Production acceptance. Never overwrite newer workspace/history data just to roll back an image.

## Current enterprise responsibilities

Private No Internet and Internet routing is deployed. `thanatcc` retains the original two runtimes and 80 legacy histories; admin now has its own private pair. Other users have private runtimes. Secure workspaces/durable state use bounded CIFS subpaths; credentials/configuration/tickets remain private local state. Internet uses separate local storage. The environments share inference and reviewed dependency artifacts, not writable projects or histories.

No Internet restricts local execution through infrastructure policy. A real remote Spark test demonstrated public TCP access from its driver and executor; the user explicitly chose to keep Livy/Spark available with that documented risk. The prepared containment patch remains unapplied. This is not solved by updating DSH. Existing AD/datalake permissions are preserved as instructed; universal read-only enforcement is not claimed.

The [risk report](DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.md) tracks those boundaries. The [LLM setup and results guide](LLM_SETUP_AND_TEST_RESULTS.md) covers the shared inference installation and observed performance separately.
