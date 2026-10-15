# Current DSH storage and persistence

The Secure and Internet execution pools use separate local TopoLVM PVCs. Secure mounts `dsh-secure-workspace` at `/workspace` and `dsh-secure-state` at `/state`. DSH_HOME points to `/state`. Internet uses its own staging and state PVCs. These volumes survive ordinary pod replacement; they do not establish central backup or node-loss recovery.

The SMB claim `da-workspace-pvc-new` points to `//bot.or.th/cfs/FILESERV/DA_WORKSPACE/workstation`. The legacy main DSH configuration mounts its `dsh` subdirectory but that deployment is scaled to zero. The new pools do not mount the share. Migration was one-time; no ongoing central synchronization is configured.

The old guide's automatic CIFS flush, zero-loss and multi-tenant-isolation claims must not be applied to the current pools. Preserve it as [historical documentation](archive/STORAGE_GUIDE_LEGACY_20261015.md).

## Correction and acceptance

1. Inventory both local and central copies; identify newer files, duplicates and conflicts without deletion.
2. Establish approved ownership, per-user/environment share ACLs and dedicated storage credentials.
3. Keep active databases and locks on storage with suitable locking semantics. Prevent multiple active writers to a state directory.
4. Use coherent database backup/checkpoint or quiesced snapshots; version the destination and verify hashes/content. Do not simply copy a live database directory.
5. Test restore into an isolated runtime, including session history and attachments; record recovery limits and failures.
6. Keep Internet staging unable to read protected source/results or approve its own dependencies.

This is the correction design, not a deployed synchronization claim. See the [security/architecture walkthrough](DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.html) for actual status, lineage and responsibilities.


## Runtime rollout verified — 15 October 2026, 20:39 ICT

Build 62702 is deployed in gateway, Secure and Internet. Read the [actual rollout procedure, restart/persistence results and rollback limitations](DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.md#safe-runtime-rollout--actual-deployed-result) and [live evidence](context-evidence/runtime-rollout-live-20261015.json). Secure retained 80 listed histories and 2,732 checked files; Internet retained controlled markers. Coherent local snapshot PVCs were retained; no central DA_WORKSPACE synchronization or full restore was established. Use Recreate and actual application health probes; do not run two state writers or co-mount live state in a verifier pod. The GPU configuration was not changed by this rollout.
