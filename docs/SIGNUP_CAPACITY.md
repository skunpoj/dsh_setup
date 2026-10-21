# Signup admission under resource pressure

The portable `scripts/signup_admission.js` evaluator accepts a trusted collector snapshot and the current registered-account count. It returns an admission decision; it never edits users, limits, routes or workloads. Run `node tests/test_signup_admission.js` for pressure, recovery, incomplete-additional-instance and stale-data cases.

For a deployment with automatic private-workspace provisioning, call the evaluator immediately before creating any account, including administrator-created users and allocation from warm spares. A denied decision must report zero admission slots and reject registration with HTTP 503 before any account or workspace assignment is written. Apply the same decision to the displayed slot count. Existing login and assigned-user routing must remain independent.

The trusted collector samples all node workloads, including notebook kernels, agents, apps and any separately operated owner-only instances. For CPU and RAM, subtract the larger of measured consumption and reservations from node allocatable capacity. Also account for pod slots and actual local-storage availability. Keep configured operating reserves plus one future private-pair budget as an admission cushion. Already-reserved spare pairs remain counted once in infrastructure planning, but do not bypass the admission cushion.

A report must be less than 60 seconds old, have node usage less than 90 seconds old, cover all configured additional instances and match the current registered-account count. Missing, malformed, stale or incomplete snapshots deny admission. See the evaluator and tests for the exact version-1 snapshot schema. Never accept collector data from an untrusted browser request.

Re-evaluate on every signup. A fresh healthy sample reopens remaining spares automatically, subject to the unchanged saved account limit. A 15-second collector interval is suitable for this sampled guard; it does not guarantee safety against instantaneous spikes or concurrent GPU inference demand. Preserve existing users and running workloads during pressure. Keep self-registration disabled on fixed-owner instances while including their resource consumption in the collector.

## Integration boundary

This public tree is a sanitized fresh-install reference. The evaluator is a reusable component, not an installed capacity controller. The reference gateway does not automatically discover or deploy an organization-specific provisioning controller. Leave self-registration disabled until your collector, private-runtime assignment and atomic account-creation path are integrated and qualified. Do not merge private deployment history into this repository.
