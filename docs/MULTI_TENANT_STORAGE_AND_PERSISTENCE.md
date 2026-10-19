# DSH storage and persistence — current deployed design

No Internet workspaces and durable histories use the original mounted DA_WORKSPACE. Each account has a private execution pair with separately scoped mounts. Internet remains separate and has no protected CIFS mount. The [central-state restoration record](context-evidence/central-state-live-20261015.json) documents the original migration; the [private-routing guide](PER_USER_ISOLATION.md) and [signup guide](SELF_SERVICE_SIGNUP.html) describe the subsequent account isolation and capacity allocation.

| Data | Live location |
|---|---|
| Private No Internet `/workspace` | CIFS claim `dsh-da-workspace-secure`, exclusive `dsh/private/<identity-or-slot-hash>/secure` subpath |
| Private No Internet sessions, attachments, storages, workspaces and logs | Direct `/state/<directory>` submounts to that identity's `dsh/private/<identity-or-slot-hash>/state/<directory>` |
| No Internet credentials and profiles | Dedicated local state PVC; Kerberos cache remains private |
| Internet workspace and state | Separate private local PVCs for the assigned Internet runtime |
| Preserved owner content | `thanatcc` retains the original `dsh` workspace and `dsh/dsh_storage` durable directories, with private-user and reviewed security subtrees masked |
| Approved packages | Read-only approved cache; Internet writes only to Incoming |

The Windows root is `\\bot.or.th\cfs\FILESERV\DA_WORKSPACE\workstation\dsh`. The historical raw USER_INPUT verifies `dsh_storage`, not `dsh_volume`. Durable content now writes centrally through mounted directories; the old 15-second copy loop is not required. Active configuration/credentials remain local and are not included in the central state-directory migration.

## Migration and compatibility

A single Secure writer was stopped before copying and hashing the current state. Prior central directories and original local state remain available. Canonical central project content takes precedence over stale project copies in local state; both conflict versions must be preserved. The live reconciliation found all 28,898 canonical project files unchanged, without conflicts.

43 legacy session records retained inaccessible `/root/...` cwd values. A reviewed explicit mapping corrected only each compressed header. Session IDs and all other header fields were preserved; the original generation files were retained and all conversation-event frames remained byte-identical. All 80 listed histories now have readable cwd paths. This is not a full tool-resumption test for every old session.

The installed DSH storage implementation passed CIFS create/flush/reopen. A separate process could not acquire the held writer lease and could acquire it after release. Across another runtime replacement, all 82 session files matched their prior hashes and four newly written marker files survived. Authenticated login/logout, held sessions and real terminal WebSocket command execution passed in both environments. Temporary acceptance credentials and markers were removed.

## Operation and rollback

Use `scripts/restore_central_state.py` only for a reviewed, stopped-writer migration with a fresh rollback directory and private acceptance probe. Keep local PVCs and previous central directories. The source procedure merges canonical central projects into the candidate before switching the durable mounts. Never use an old local state copy to hide newer CIFS writes during rollback; first reconcile and preserve both versions.

CIFS maps UID/GID 10001 with `forceuid`, `forcegid`, `dir_mode=0770`, `file_mode=0770`, `vers=3.0`. This is not per-file POSIX permission enforcement or proof of Windows/server ACL correctness. A live share is not a backup, immutable archive or zero-loss guarantee; independent storage-server recovery and access review remain necessary.

## Per-user storage and signup

Private routing is deployed. Each account/environment uses a separate execution runtime and scoped storage; the gateway mounts launch tokens and account metadata, not user workspace roots. The preserved legacy owner retains its original data. Explicitly authorized admin support copies are independent records, not a shared live history store.

Self-service signup binds an account to one unused qualified slot. The slot's opaque identifier determines its pre-provisioned PVCs and CIFS subpaths; a submitted username does not construct a filesystem path. Account and slot assignment persist together. No Internet and Internet keep separate sessions, attachments and credentials. Disabling an account does not free or recycle its volumes. Test pairs never enter the live catalog. Operators add new empty pairs rather than reusing another person's state.

Datalake access is independent: user-specific Kerberos and existing AD/Hive/HDFS rights are preserved. A workspace mount grants no datalake entitlement and imposes no universal read-only policy. The earlier [design audit](DA_WORKSPACE_DESIGN_REVIEW_20261015.md), [workspace restoration](context-evidence/central-workspace-live-20261015.json) and [migration experience](CENTRAL_STATE_RESTORATION_20261015.md) retain their historical scope.
