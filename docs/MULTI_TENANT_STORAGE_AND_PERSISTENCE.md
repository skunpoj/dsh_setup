# DSH storage and persistence — verified 15 October 2026, 21:32 ICT

## Actual mounts

| Data | Live location | Scope |
|---|---|---|
| Secure workspace | CIFS `//bot.or.th/cfs/FILESERV/DA_WORKSPACE/workstation`, claim `dsh-da-workspace-secure`, subpath `dsh`, mounted at `/workspace` | Actual central workspace restored; writes go directly to the share |
| Active Secure state | Local TopoLVM claim `dsh-secure-state`, mounted at `/state`; DSH_HOME resolves here | Existing histories and runtime locking preserved |
| Internet workspace/state | Separate original staging/state PVCs | Does not mount protected DA_WORKSPACE |
| Central history baseline | `dsh-storage-recovery/20261015142136/secure-state-history.tar.gz` on the share | Coherent stopped-writer baseline; 29,067 extracted files verified |
| Local rollback workspace | Original `dsh-secure-workspace` PVC retained | Not deleted or overwritten during reconciliation |

CIFS maps UID/GID 10001 with `uid`, `gid`, `forceuid`, `forcegid`, `dir_mode=0770`, `file_mode=0770`, `vers=3.0`. Non-root direct script execution passed. Both inspected Git repositories already use `core.filemode=false`. Forced CIFS modes do not provide per-file POSIX permission semantics; the active provider credential file remains on local state with its original protection.

## What was corrected

The [raw transcript/Git review](DA_WORKSPACE_DESIGN_REVIEW_20261015.md) identified the assistant's unrequested replacement of DA_WORKSPACE with local workspace storage. The correction restores the actual mount, rather than substituting backups for it. It does not grant new RDT permissions or redistribute histories between accounts.

Secure was stopped before reconciliation. Of 2,651 local files, the first pass found 2,650 unchanged and copied one new file. No conflicts occurred; all 29,064 central-only files were retained. Before cutover, a second pass verified all 2,651 local files matched centrally. The reconciliation code preserves an old central version before replacing a differing file, rejects unsafe paths/types, and never deletes destination-only files. Source tests exercise conflicts and collision rejection.

The first history restore check used a Python API unsupported by the image and triggered automatic rollback to local mounts. A portable path/type-checked extractor replaced it; the existing central archive was restored into `dsh-cifs-reconcile-20261015142136-restore` and 29,067 files read back successfully. The final cutover reused that verified coherent baseline rather than claiming it represented later state changes.

## Actual post-cutover tests

- `/proc/mounts` reports CIFS at `/workspace`; runtime UID remains 10001.
- A runtime-written marker was read from an independent pod; that pod wrote a reply read by the runtime.
- A second Secure restart retained both marker contents and the central mount; all 2,651 original files were then read back through the actual runtime and matched the manifest.
- Fresh login/logout and held sessions passed; Secure's actual list API still returned 80 histories.
- Internal inference returned the exact expected sentinel; representative public HTTPS still failed.
- Temporary account and own test markers were removed; the original volumes and central-only files remain.

[Recorded live evidence](context-evidence/central-workspace-live-20261015.json) binds these checks to the mounted claim and unchanged runtime digest. The GPU/inference deployment and Internet runtime were not restarted by this correction.

## Remaining persistence and security limits

The workspace is now mounted centrally. Active state remains local, with a separately verified central point-in-time baseline. **There is no continuous state synchronization**, no promise of zero loss of new state after node failure, and no full restored-runtime boot test. Do not describe the baseline as current live history replication.

The central archive excludes top-level `/state/.credentials.yaml`, but histories/storages may still contain sensitive user content. Recovery folders require reviewed server-side access controls and retention. The main runtime mounts only `dsh`; it does not mount the recovery folder. This does not establish all Windows/share-user ACLs.

Per-user runtime source now uses distinct central workspace subpaths, but private runtime cutover, pilot identity approval, read-only RDT source access and cross-user acceptance remain separate work. Never expose the entire share to each runtime or to Internet staging.

## Operator procedure

Use `k8s/dsh-da-workspace.yaml` for the reviewed claim. Keep legacy PVs and local rollback PVCs. `scripts/restore_central_workspace.py` stops Secure, reconciles and verifies content, applies the bounded mount, then checks actual held/fresh gateway sessions. It restores the original deployment specification on failure and preserves both data locations. Always use a fresh rollback directory and reviewed targets.

Do not rerun the historical migration job to revert this mapping. Before any later rollback, account for new writes already committed to CIFS; restoring a local mount must not hide them without a recorded reconciliation. Preserve source and central recovery material until independently verified recovery is available. Use the [security walkthrough](DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.html) for the three pilot controls and evidence limits.


## Follow-up: environment boundaries and legacy session cwd

A fresh read-only mount/API review confirms Secure workspace is CIFS, Internet workspace/state are separate local volumes, and both active DSH homes resolve to their own local `/state`. The user-supplied raw engineering export names `dsh_storage`, including a direct 12 October UNC path; no `dsh_volume` text match was found in that bundle. Historical DSH2 zero-CIFS policy and the new Internet environment selection are separate concepts.

Legacy background/preStop mirroring to `/workspace/dsh_storage` has not been restored in the new pools. Existing central session folders are historical copies, not evidence of current synchronization. An additional compatibility gap is now verified: 43 of the 80 listed Secure session records retain inaccessible `/root/...` working directories; 37 point to readable `/workspace/...` paths. This does not establish that all 80 can resume tool execution. No session records or runtime settings were changed in this follow-up. See [raw-source provenance and live path checks](context-evidence/environment-session-storage-review-20261015.json).
