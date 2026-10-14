# DSH upstream synchronization and internet policy

## Deployed source layers

The deployment installs a published `@deepseek-ai/dsh` package and then applies repository-owned configuration and compatibility patches from `scripts/configure_models.js`. The enterprise authentication gateway in `scripts/auth_proxy.js` is also repository-owned. These files are overlays; they are not part of the official DeepSeek Harness repository.

The current upstream comparison is:

| Item | Revision inspected |
| --- | --- |
| Deployed package baseline | `dsh-v0.2.0-rc.2` |
| Official upstream | `deepseek-ai/deepseek-harness` `master` at `571902028a75c64c1d767f4ae5fd099485f0ddf0` |
| Latest upstream tag inspected | `dsh-v0.2.1-alpha.3` (`2fbf4359b8`) |

The upstream interval changes thousands of files and includes Session v4 persistence, remote-access principals, permission policy, web tools, sandbox behavior, compaction, attachment handling, plugin composition, and the Web client. Treating it as a drop-in package update would put stored sessions and runtime byte patches at risk.

## Synchronization procedure

1. Record the deployed package version, running image digest, ConfigMap hash, and a backup of `/workspace/dsh_storage`.
2. Fetch official upstream tags into a separate checkout. Never merge upstream source into this deployment repository.
3. Compare the next published tag with the pinned baseline. Review Session format and upgrade guides first, followed by every package file currently modified by `configure_models.js`.
4. Build a candidate image that already contains the selected DSH package and operating-system dependencies. Do not depend on network package installation during pod startup.
5. Reapply each enterprise requirement through documented configuration or a Cordis plugin when upstream exposes an extension point. Retain byte patching only when no supported extension exists, and make every patch fail loudly when its expected source text changes.
6. Restore a copy of Production data into an isolated candidate environment. Verify login, existing Session reads, new prompts, compaction, attachments, model calls, tools, terminal, dynamic application proxy, and orderly restart persistence.
7. Deploy with a rollback image and the preserved ConfigMap. Read back the running image digest and mounted scripts, then repeat the affected behavior tests.

## Internet selection on the login page

The enterprise login page provides `Off` and `On`, with `Off` selected when the form is first displayed. On successful login the gateway:

- validates the credential before accepting the selection;
- stores the user's most recent selection in `/workspace/users/.user_settings.json` with mode `0600`;
- binds the selection to the new in-memory authenticated session;
- exposes the authenticated result at `GET /api/auth/session`; and
- forwards `X-DSH-Internet-Access: off|on` and `X-DSH-User` to the DSH Web service.

This is a verified user-policy transport, not a complete egress firewall. The current DSH, terminal, and user applications share one pod network namespace, and the live namespace has no NetworkPolicy. A process in that pod can currently reach public sites regardless of the login selection. Do not describe `Off` as enforced internet isolation until the deployment separates offline and online execution into different pods or another kernel-enforced network boundary consumes the authenticated policy.

## Required enforcement architecture

Use two execution pools behind the authenticated gateway:

- an offline pool with default-deny egress and explicit DNS plus in-cluster LiteLLM access;
- an online pool with the approved outbound policy; and
- routing that binds each authenticated Session to exactly one pool for its lifetime.

The DSH package and dependencies must be baked into an image so the offline pool can start without public package repositories. Session storage must be tested for concurrent access before both pools mount the same persistent data. Until those conditions are met, retain the login selection as policy metadata and do not deploy it as a security control.
