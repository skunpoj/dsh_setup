# DSH storage and persistence — current deployed design

The [latest live record](context-evidence/central-state-live-20261015.json) supersedes the earlier local-only active-history snapshot. Secure uses the actual original mounted DA_WORKSPACE. Internet remains separate and has no protected CIFS mount.

| Data | Live location |
|---|---|
| Secure `/workspace` | CIFS claim `dsh-da-workspace-secure`, subpath `dsh` |
| Secure sessions, attachments, storages, workspaces and logs | Direct submounts under `/state/<directory>` to `dsh/dsh_storage/<directory>` on the same CIFS claim |
| Secure credentials and profiles | Original local `dsh-secure-state` PVC |
| Internet workspace and state | Separate local `dsh-internet-staging` and `dsh-internet-state` PVCs |
| Approved packages | Read-only approved cache; Internet writes only to Incoming |

The Windows root is `\\bot.or.th\cfs\FILESERV\DA_WORKSPACE\workstation\dsh`. The historical raw USER_INPUT verifies `dsh_storage`, not `dsh_volume`. Durable content now writes centrally through mounted directories; the old 15-second copy loop is not required. Active configuration/credentials remain local and are not included in the central state-directory migration.

## Migration and compatibility

A single Secure writer was stopped before copying and hashing the current state. Prior central directories and original local state remain available. Canonical central project content takes precedence over stale project copies in local state; both conflict versions must be preserved. The live reconciliation found all 28,898 canonical project files unchanged, without conflicts.

43 legacy session records retained inaccessible `/root/...` cwd values. A reviewed explicit mapping corrected only each compressed header. Session IDs and all other header fields were preserved; the original generation files were retained and all conversation-event frames remained byte-identical. All 80 listed histories now have readable cwd paths. This is not a full tool-resumption test for every old session.

The installed DSH storage implementation passed CIFS create/flush/reopen. A separate process could not acquire the held writer lease and could acquire it after release. Across another runtime replacement, all 82 session files matched their prior hashes and four newly written marker files survived. Authenticated login/logout, held sessions and real terminal WebSocket command execution passed in both environments. Temporary acceptance credentials and markers were removed.

## Operation and rollback

Use `scripts/restore_central_state.py` only for a reviewed, stopped-writer migration with a fresh rollback directory and private acceptance probe. Keep local PVCs and previous central directories. The source procedure merges canonical central projects into the candidate before switching the durable mounts. Never use an old local state copy to hide newer CIFS writes during rollback; first reconcile and preserve both versions.

CIFS maps UID/GID 10001 with `forceuid`, `forcegid`, `dir_mode=0770`, `file_mode=0770`, `vers=3.0`. This is not per-file POSIX permission enforcement or proof of Windows/server ACL correctness. A live share is not a backup, immutable archive or zero-loss guarantee; independent storage-server recovery and access review remain necessary.

## Isolation and remaining acceptance

Current Secure users still share a runtime and central environment tree. The private-runtime generator scopes every workspace and durable-state mount to its identity. Source tests verify no overlap between generated users, but private-user cutover has not occurred. Broad legacy shared mounts must not expose future private paths when claiming user isolation. Do not infer ownership of the existing shared histories or copy them into every user.

Read-only RDT source access remains separate from restoring the original writable workspace. It requires the exact approved source/snapshot/view, named identities and source-write/out-of-scope-read negative tests. The earlier [design audit](DA_WORKSPACE_DESIGN_REVIEW_20261015.md) and [21:32 workspace-only evidence](context-evidence/central-workspace-live-20261015.json) remain historical records. See [deployment experience](CENTRAL_STATE_RESTORATION_20261015.md).
