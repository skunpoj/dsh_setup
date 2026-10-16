# DSH upstream maintenance and release policy

## Why this is not a fully synchronized source fork

`dsh_setup` packages the official npm distribution and maintains deployment, authentication, routing, storage and model-configuration overlays. It does not copy the official monorepo. Updating the official package and preserving these overlays is the correct synchronization operation; merging all official source files into this deployment repository would mix two different repository purposes.

Fresh checks on 16 October 2026 found:

| Item | Observed value |
|---|---|
| Running DSH package and Dockerfile pin | `0.2.0-rc.2` |
| npm latest / next | `0.2.0-rc.2` / `0.2.0-rc.2` |
| npm alpha | `0.2.1-alpha.4` |
| Official master | `86a402200d95fecef4529d969836f1fe13c6cb0d` |

The installed package therefore matches the default published release channel. It is behind the newest preview source, not behind npm latest. The older master/tag comparison is superseded by [the current channel check](context-evidence/upstream-check-20261016.json). Explicit preview detection is recorded separately; the preview has not been built or deployed by that metadata check.

Upstream describes DSH as developer-preview software with breaking changes. See the [official README](https://github.com/deepseek-ai/deepseek-harness/tree/86a402200d95fecef4529d969836f1fe13c6cb0d#developer-preview) and [safety guidance](https://github.com/deepseek-ai/deepseek-harness/blob/86a402200d95fecef4529d969836f1fe13c6cb0d/SAFETY.md).

## Automated checking and candidate patching

No release-check workflow was configured previously. The prepared local `.github/workflows/upstream-candidate.yml` defines:

1. Daily release checks at 02:17 UTC (09:17 ICT), plus manual dispatch and checks when the detector/workflow changes.
2. Tracking npm latest by default. A manual `candidate_version` can explicitly select a preview.
3. A candidate Docker build and authentication/routing/catalog/package tests when the selected version differs.
4. A package-pin branch and PR only after those candidate tests pass. Existing branches are retained rather than overwritten.
5. No auto-merge, image publication or Production deployment in this GitHub workflow.

**Publication status:** GitHub rejected the workflow push because the stored PAT lacks workflow permission. The implementation is preserved locally and in the Azure reference copy, but no GitHub schedule is active. Update the existing GitHub credential’s workflow-write permission through the normal credential manager, then publish the prepared file. No token value belongs in this document or chat.

The workflow requires GitHub Actions to be enabled and the repository setting allowing Actions to create pull requests. Hosted execution/PR permissions are separate from local detection tests. A default-channel check with no version change skips build and PR creation. Scheduled execution is defined only in the GitHub repository; the copy inside Azure is reference source, not another scheduler.

To reproduce detection locally:

```powershell
python scripts/check_upstream.py --output upstream-check.json
python scripts/check_upstream.py --candidate 0.2.1-alpha.4 --output preview-check.json
```

`--prepare-candidate` changes only the Dockerfile pin. Neither command installs packages into Production. Candidate version input is validated before registry lookup/preparation. Detection does not claim that text patches rebase themselves correctly.

## Why Production upgrades remain gated

Our compatibility layer still modifies selected package files. Some changes use text anchors; not every anchor is guarded by a full source contract. Candidate build/catalog tests cover known requirements, not every future upstream semantic change. Prefer supported configuration/plugins over text patching as extension points become available; do not claim that migration is already complete.

Before deployment, qualify copied-state session reads, new prompts, compaction, attachments, tools, browser Host/Origin handling, HTTP/WebSocket terminal/application proxy, private-user/network boundaries and restart/restore. Review any unmatched patch target. Retain a compatible old image/configuration and coherent state recovery baseline. Read back the actual running image and test the affected behavior after cutover.

A passing build is a candidate result, not migration or Production acceptance. Never overwrite newer workspace/history data just to roll back an image.

## Current enterprise responsibilities

Private No Internet and Internet runtimes are deployed for eight non-admin accounts; admin retains the original two runtimes and 80 legacy histories. Secure workspaces/durable state use private CIFS subpaths; credentials/configuration/tickets remain private local state. Internet uses separate local storage. The environments share inference and reviewed dependency artifacts, not writable projects or histories.

No Internet restricts local execution through infrastructure policy. A real remote Spark test demonstrated public TCP access from its driver and executor; the user explicitly chose to keep Livy/Spark available with that documented risk. The prepared containment patch remains unapplied. This is not solved by updating DSH. Existing AD/datalake permissions are preserved as instructed; universal read-only enforcement is not claimed.

The [risk report](DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.md) tracks those boundaries. The [LLM setup and results guide](LLM_SETUP_AND_TEST_RESULTS.md) covers the shared inference installation and observed performance separately.
