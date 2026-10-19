# Managed startup qualification — 19 October 2026

The main implementation separates admin approval of process startup from URL publication. New definitions are stopped until approved. Definitions remain on a dedicated gateway-controlled volume; each runtime mounts only its own policy directory read-only and writes a separate, bounded-capacity status volume. No worker writes on shared control storage.

## Disposable acceptance

- The installed production notebook worker image ran actual managed JupyterLab and a Python app. The gateway image was kept separate; an initial fixture image mismatch was corrected before notebook acceptance.
- Gateway and worker pods were replaced. Both services returned without a manual launch. The worker UID changed, the application boot counter increased, and a saved notebook remained readable.
- Account, URL, quota and startup-definition hashes remained unchanged across the replacement cases. Project source and notebook hashes were unchanged. A final replacement preserved one DSH history and its two session files exactly.
- Admin Stop survived another worker replacement and prevented both servers from starting. Admin Start and Restart were exercised through the actual dashboard and recorded in the video.
- Killing the managed app caused automatic recovery while the notebook stayed available. A repeatedly failing script entered backoff; five failures were observed in the bounded test rather than a continuous launch loop. The configured delay ceiling is 60 seconds.
- A foreign process occupying the selected port remained alive. The supervisor reported the conflict and did not kill it, including when the managed definition was stopped.
- The policy mount refused writes; gateway accounts, agent history, runtime launch-token mounts and model-key environment were absent from the supervised application context.
- The final separate-status-PVC topology was installed and its actual automatic startup was repeated successfully. Oversized status input becomes unknown in the gateway rather than an unbounded read.
- The exact final gateway source passed the isolated two-account/four-runtime signup, native DSH reply, terminal, restart-persistence, default-Internet-denial and cross-user/environment denial checks.

## Installation safeguards

The installer preserves the worker image and original mounts, snapshots native history IDs and all session-file hashes, checks non-root identity, verifies durable markers and rolls back the deployment specification on a regression. It defers active DSH agents or manually running notebooks. Existing data is never restored from an older snapshot during rollback.

Prepared signup templates strip old supervision and policy/status mounts; new runtimes receive independent startup provisioning instead of inheriting another user's service definitions. The existing file-based policy store remains single-writer. Scope and final installed/deferred counts are reported by the operator's rollout receipt, separately from these disposable cases.

See [architecture, installation and permissions](APP_SERVICE_SUPERVISION.md), [admin instructions](ADMIN_USAGE_TELEMETRY.md) and [recorded startup workflow](APP_AUTOSTART_WALKTHROUGH.html).
