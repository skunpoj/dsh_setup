# Source-grounded repository review

Large context capacity does not guarantee correct quotations or supported conclusions. Repository review therefore has two acceptance steps: mechanical checks against frozen source text, followed by a separate review of what the cited text actually establishes.

## Controlled revision

The citation revision uses the same 338 source blocks, question list and held-out reference key as the first realistic review. Only the review instructions and provenance prefix change. The previous response and answer key are excluded from model input. This is a targeted regression comparison, not an unseen general-accuracy benchmark. “Current” means the frozen repository version, not a fresh deployment observation.

The instructions require canonical answer values, citations to the requested current file and actual definition, contiguous short verbatim quotations, and narrative ranges no longer than 12 lines. They distinguish configuration, historical checkpoints, recorded tests and recommendations. They prohibit deriving an exclusive architecture, an absence claim or effective network enforcement from insufficient source evidence.

## Acceptance and correction

`evaluate_repository_review.py` checks values, requested source/definition lines, exact quotations, ranges, source diversity, actual token usage and persisted input. It cannot establish narrative entailment. `extract_repository_review_citations.py` prepares the exact cited spans for that separate review.

Review each material claim against the actual cited lines, including historical/current boundaries, host/GPU memory distinctions, actual assertions versus comments, private routing versus bootstrap defaults, and additive network policies. Record unresolved findings rather than silently fixing the raw model response.

`assess_repository_revision.py` requires the mechanical conditions, requested word range, completed narrative review and individual disposition of the seven original findings. The review must match the original assistant-text SHA-256. Missing review, changed output or an unresolved finding prevents acceptance. The script checks the recorded review conditions; it does not replace reviewer judgment or independently prove the review was correct.

The grounded-narrative mode also requires seven generated `claim_checks` entries. `evaluate_narrative_regressions.py` distinguishes restore-hash/byte checks from mount preservation, later concurrent-edit refusal from candidate construction, actual sidecar insertion from its declaration, tokenizer invocation from returned-ID validation, scoped transport assertions from a live test, and acknowledged probe-abort conversion from its catch. It checks exact short quotations, the actual supporting branch and coverage of that branch in the narrative itself. A correct ledger cannot mask the old incorrect narrative citation. These are targeted regression checks, not a general semantic verifier.

Full generated-response acceptance applies only to the unedited DSH response. An editorially corrected publication is a separate artifact and cannot turn a failing generated narrative into a passing one. Any correction turn must be generated in DSH, saved separately, checked again and identified in the results. Previous failed drafts remain retained.

Preserve each submitted prompt hash and original response. If editorial corrections are published, identify them as reviewed corrections rather than original model output. Report any remaining defects even when inference and fact retrieval succeed.

## Shared-service test boundaries

Use an explicitly allowlisted disposable runtime with empty state/workspace volumes. Check both GPU activity and the actual long-admission lease before starting. Run paired ordinary DSH conversations during the long turn and inspect their exact answers and persistence. Separate replies during admission waiting from those overlapping admitted processing. Keep the model identity/restart count, preparation and generation timing, retries and memory warnings in the result.

Archive and hash-verify the disposable session files before deleting the runtime. Confirm ordinary inference and admission availability afterward. Deleting a runtime alone does not establish upstream cancellation. These tests do not modify user histories, ownership, storage mounts or shared inference settings.
