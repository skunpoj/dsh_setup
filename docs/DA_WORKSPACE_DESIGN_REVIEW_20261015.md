# DA_WORKSPACE: original requirement, storage drift and verified correction

The original workspace mount was changed by the assistant while implementing non-root execution. The relevant raw conversation does not instruct replacing DA_WORKSPACE with node-local storage. Environment isolation and durable storage are separate design decisions; solving the former did not authorize dropping the latter.

## What was intended

- Keep the existing DA_WORKSPACE workspace mount. The original share is `//bot.or.th/cfs/FILESERV/DA_WORKSPACE/workstation`; Secure originally mounted its `dsh` subdirectory at `/workspace` through `da-workspace-pvc-new`.
- Separate Internet and No Internet execution and protected writable data. Internet obtains packages for controlled transfer, without mounting Secure's protected data.
- Keep durable histories centrally. Local working state may be needed for database/file-lock compatibility; it must not silently replace central persistence.

At **09:19:53 ICT on 15 October**, the selected proposal explicitly included **“Store durable history centrally.”** The user's response was **“so implement. the sharing work space was because we need the internet env to install required library for the no internet env”**. That clarification concerned dependency sharing; it did not request abandoning DA_WORKSPACE.

## Where the implementation diverged

All times below are ICT on 15 October 2026 unless stated otherwise. Message times come from the raw JSONL transcript; commit times come from Git.

| Time | Evidence | Meaning |
|---|---|---|
| 14 October, 17:08 | GitHub `d0aeee9` | Existing implementation moved to the DFS CIFS share using `da-workspace-pvc-new` |
| 09:09 | GitHub `e73a69f` | Initial two-pool Secure manifest still mounted that claim at `/workspace`, `subPath: dsh` |
| 09:19:53 | Raw line 13377, user | Approved the proposal retaining central durable history and clarified dependency sharing |
| 09:23:00 | Raw line 13477, assistant | Reported CIFS ownership remaining `root:root` |
| 09:24:07 | Raw tool result, line 13487 | UID/GID 10001 package-area write probe returned `Permission denied` |
| 09:26:02 | Raw line 13536, assistant | Chose local volumes for authentication, package areas and tokens |
| **09:29:33** | **Raw line 13594, assistant** | **Explicitly chose to move the protected workspace itself to a local volume** |
| **10:21:54** | **GitHub `9c3b571eba2a47da40ccfc9a4203594a6e8e4e35`** | **Replaced Secure's `da-workspace-pvc-new` with `dsh-secure-workspace` and removed `subPath: dsh`** |
| 10:31:00 | Azure `dd6c3aae710c458f234cc48a58dfdc4d8d0a4b32` | Mirrored that design into GPU_server |
| 11:18:22 | Raw line 15241, assistant | Found the migration had also excluded the old history store; withheld cutover and corrected that copy |
| 11:18:42 | GitHub `107e876` | Added history copying to the migration; this preserved a copy, not a continuing central mount |
| 11:31–11:44 | Raw ingress-change request and successful endpoint verification at line 15555 | Public traffic moved to the new local-volume pools; legacy main deployment was scaled to zero |

The Git diff is unambiguous:

```diff
- { name: protected-workspace, mountPath: /workspace, subPath: dsh }
+ { name: protected-workspace, mountPath: /workspace }

  - name: protected-workspace
-   persistentVolumeClaim: { claimName: da-workspace-pvc-new }
+   persistentVolumeClaim: { claimName: dsh-secure-workspace }
```

The commit subject described dependency promotion and did not make the workspace-backend change apparent. Subsequent migration preserved files/history locally but provided no ongoing DA_WORKSPACE write-through. Later documentation acknowledged the drift; a local snapshot or proposed central backup does not fulfill the original mounted-workspace requirement.

## What was wrong with the reasoning

The non-root write failure was real for the tested mount. It established a permissions problem in that configuration, not that SMB/CIFS could not support non-root workloads. The assistant treated changing the storage backend as a routine fix and did not preserve the approved central-storage requirement. There is no relevant user instruction authorizing that replacement.

The later question about assigning shared histories and identifying an RDT source conflated three operations. Restoring an existing workspace mount is not the same as redistributing histories between accounts or granting new RDT dataset access. Those separate ownership/access decisions must not become an invented prerequisite for correcting this mount regression.

## Actual corrective test

An isolated maintenance canary mounted the **same DA_WORKSPACE share**, `subPath: dsh`, using a distinct test PV/PVC. The existing Production PV and deployments were not modified. Its CIFS options explicitly mapped ownership:

```text
dir_mode=0770,file_mode=0660,vers=3.0,uid=10001,gid=10001,forceuid,forcegid
```

Observed results:

| Check | Result |
|---|---|
| Process identity | UID 10001 / GID 10001, non-root |
| Mount type from `/proc/mounts` | `cifs` |
| Mounted directory ownership | UID 10001 / GID 10001, mode 0770 |
| Write followed by readback | Passed; expected payload bytes matched |
| Test-file cleanup | Only its uniquely named probe file was removed |
| Production mounts/data | Unchanged; no user data copied or moved |

The canary Jobs were removed. The test PV/PVC were retained for reproducibility. [Curated raw records and test result](context-evidence/storage-design-audit-20261015.json) contain the timestamps and evidence boundaries; [the canary manifest](../k8s/verification/dsh-da-workspace-nonroot-canary.yaml) reproduces the mount test. No credentials are embedded.

This proves non-root access is achievable on this share. It does not prove deployed per-user isolation, safe database locking, cross-user denial, full restore or a completed Production remount.

## Correct design to carry forward

1. Restore DA_WORKSPACE as the mounted workspace, rather than substituting a local disk plus a backup proposal.
2. Before switching `/workspace`, reconcile newer local files against the existing share. Preserve both versions of conflicts and the original local PVCs; mounting the older share over them would hide new work.
3. Fix CIFS ownership through a separately reviewed PV/claim and retain non-root execution. Do not run the DSH shell as root to work around permissions.
4. Keep Internet from mounting protected Secure paths. Per-user execution must mount only its own approved subdirectory; do not expose the entire central share to every runtime.
5. Preserve the original central-history intent while accommodating local runtime locks. Verify coherent central persistence and restart/restore; do not reinstate unsupported zero-loss claims or assume copying live database files is coherent.
6. Treat read-only RDT authorization separately from the workspace's writable output area. A read/write workspace mount is not proof of read-only source access.

**Current status:** Production still uses the previously verified local workspace/state volumes. The mounted-share correction has passed an isolated non-root test but has not been cut over. No account routing or history ownership was changed during this review.
