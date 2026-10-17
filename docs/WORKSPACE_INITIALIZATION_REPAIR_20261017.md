# Default workspace repair — 17 October 2026

The admin screenshot reported “Unable to create default workspace.” The relevant private workspace and history mounts were writable. The installed first-use controller invoked Linux `xdg-user-dir DOCUMENTS`; the runtime image has no such utility, and the actual resolver returned `spawn xdg-user-dir ENOENT`. Therefore this was a missing desktop-directory resolver/configuration defect, not proof of missing CIFS data or a reason to weaken user isolation.

## Repair

The supported `workspace-controller` option `documentsDirectory: /workspace` bypasses desktop lookup. DSH creates its default beneath `/workspace/deepseek-harness/default-workspace`, inside the existing private persistent mount. The seed profile and startup script now configure that option; startup persists a private rollback profile, refuses concurrent edits and reads back the setting. No package download or root privilege is needed.

The pictured admin runtime was repaired immediately through the authenticated DSH `workspace/create` API using its existing `/workspace`. Its registry was then read back, and the session-file fingerprint stayed unchanged during that operation. A restart check additionally exposed that the old bootstrap used the migrated-away `settings.yaml` as its initialization sentinel and recopied seed profiles on restart. The sentinel now checks the actual web profile instead. The admin's No Internet runtime uses an immutable bootstrap overlay that preserves that profile and reapplies the explicit controller setting; its registry and session fingerprint are checked after replacement. Main private runtimes with an existing registry were left intact; empty registries were registered through the same API. This adds workspace metadata without moving files, copying other users' histories or replacing the mounted storage. Other users and the model were not restarted by this repair.

## Verification and deployment boundary

A disposable runtime with fresh empty storage and no Production PVCs successfully executed the actual `workspace/initializeDefault` RPC. It returned the expected persistent-scope path, saved the registry and passed a write/read/delete marker. The local regression test verifies that the profile patch is idempotent and preserves unrelated model/controller settings. Main-runtime registration results are recorded separately. These API and persistence checks do not claim that the user's already-open browser has refreshed or selected the new row.

The live admin profile and existing empty registries are repaired. Future-image seed/startup changes are source changes until the normal image-build rollout; current main images were not rebuilt for this repair. The admin has the tested bootstrap overlay; the other runtime registries were repaired without restarting them. Existing registries avoid the failed first-use lookup. Newly provisioned empty runtimes should use the patched image or have the explicit controller setting applied before launch.

Refresh the DSH browser and select the now-registered workspace. Empty private admin history is independent of the preserved `thanatcc` histories; no histories are reassigned to admin.

[Fresh-runtime RPC acceptance](context-evidence/workspace-default-canary-20261017.json) and [main registry readback](context-evidence/workspace-registries-live-20261017.json) distinguish the synthetic test from the live repair.

A fresh browser against the actual admin runtime rendered the registered workspace and composer without the failure toast. This used an operator-only local port forward and does not claim that the user's already-open browser refreshed. Across the 20 main runtimes, 18 empty registries were repaired and two existing registries were preserved.
