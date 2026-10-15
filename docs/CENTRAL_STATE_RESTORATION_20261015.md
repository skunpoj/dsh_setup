# Central durable state restoration — 15 October 2026

This deployed result supersedes the earlier statement that all active histories remain local. The original requirement is the mounted DA_WORKSPACE, not a backup substituted for that mount.

## Implementation

Secure retains its original local `/state` root for credentials, profiles and configuration. Separate submounts bind `/state/sessions`, `/state/attachments`, `/state/storages`, `/state/workspaces` and `/state/logs` directly to `dsh/dsh_storage/<directory>` on the same CIFS claim used by `/workspace`. New durable content therefore reaches central storage directly; no periodic copying loop is needed. Internet retains separate local storage and no protected CIFS mount.

Only one Secure writer is allowed. The operator stops Secure, copies the current local durable directories to a fresh candidate on CIFS and hashes every file against the stopped source. Previous central directories are moved into a distinct recovery location; destination-only historical content is retained there. Credentials and local profiles are not included in that copy. The old local state claim remains available for rollback.

Legacy session cwd correction is explicit metadata migration: `/root/<project>` maps to the already existing `/workspace/dsh_storage/workspaces/<project>`; `/root` maps to `/workspace`. Unmapped root paths, absent targets and destination collisions cause refusal before mutation. The compressed first frame contains exactly one header. Only its `cwd` field changes; the remaining compressed conversation-event frames must be byte-identical by SHA-256. Session IDs and all other header fields are preserved. Original generation files are retained in recovery. This is not a blanket string replacement in conversations.

## CIFS compatibility and experience

The actual installed DSH persistence backend created, flushed and reopened a synthetic session on CIFS. An independent process received `EACCES: flock failed` while the first writer held the lease, then acquired the writer successfully after release. The initial test harness incorrectly classified the generic `EACCES` error; the corrected test verifies both denial while held and acquisition after release. Early harness attempts omitted required V4 header fields; those failed test setup and do not count as persistence failures or successful acceptance.

Source tests cover conversation-byte preservation, recovery originals, unmapped-root refusal, destination-collision refusal, exact rollback on worker failure and distinct per-user central mount paths. Generator tests are source evidence; they do not establish deployed per-user isolation.

## Deployment and acceptance

The live evidence JSON records stopped-source file verification, corrected record counts, actual mounts, post-restart history/path checks, login/logout behavior and external-denial/internal-inference checks. Neither history listing nor cwd accessibility establishes full tool resumption for every historical session. No near-1M load test or model restart is part of this storage deployment.

Rollback restores the saved deployment specification and retains both storage copies. If users have written new data after cutover, reconcile those central writes before any later rollback; never silently hide them behind the older local mount. A live central mount is not a backup, storage-server disaster recovery or proof of server-side ACL adequacy.

Per-user runtime cutover, assignment of existing shared histories and read-only access to an approved RDT source remain separate acceptance work. The broad legacy shared `dsh` mount must not remain able to access future private user directories when claiming cross-user isolation.

## Verified live result — 2026-10-15T22:17:54.742424+07:00

- 29,078 stopped-state files copied and hash-verified before cutover.
- 43 session cwd headers corrected; all 43 compressed conversation-event tails remained byte-identical.
- 28,898 canonical central project files reconciled and read back; all unchanged, no conflicts. The initial cutover copied duplicate local project state; an additional stopped reconciliation confirmed no content divergence. The retained procedure now reconciles canonical projects before cutover.
- 80 histories listed and 80 cwd paths readable, with zero `/root` cwd records.
- 82 session files stayed byte-identical across a further process replacement; four new durable-directory markers survived and were removed.
- Fresh and held authenticated sessions, logout invalidation and actual terminal WebSocket execution passed in both environments at UID 10001.
- Secure GitHub/PyPI/npm probes timed out; Internet returned HTTP 200 for each. Both returned the exact internal inference sentinel.
- Temporary acceptance account removed; other accounts unchanged. GPU model and Internet runtime were not restarted by this storage work.

See [live evidence](context-evidence/central-state-live-20261015.json). Per-user and approved RDT acceptance gaps remain open.
