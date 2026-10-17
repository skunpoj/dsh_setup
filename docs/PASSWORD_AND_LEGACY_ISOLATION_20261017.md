# Password storage and legacy isolation — 17 October 2026

## Result and scope

The main gateway and both legacy authentication services now use salted scrypt password records. DSH2 (`user2`) and DSH3 (`user3`) are single-owner, non-root private runtimes. Their owner credentials, original workspaces and histories were preserved. Main No Internet/Internet routing and Livy/Spark availability were retained. This is an implementation and bounded acceptance record, not a claim that all residual risks are closed.

The three-risk explanation is in [the risk report](DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.html). The final [live acceptance](context-evidence/password-legacy-final-live-20261017.json) supersedes the earlier migration/network snapshots for current legacy UID, account count and audit aggregation. Historical snapshots retain their original observations.

## Identity and storage boundaries

- Main accounts retain fixed private user/environment routing. Existing owner `thanatcc` and admin roles are unchanged.
- Each legacy hostname admits only its configured owner. Disabled guest/cross-account verifiers are retained in an operator-only Secret, not in the worker filesystem. There is one active hashed record per legacy instance.
- Each legacy execution container runs UID/GID 10001, without privilege escalation, Linux capabilities or an API token. It uses the immutable managed-tools image, not apt/npm downloads at startup.
- A trusted, bounded root initialization step prepares only the instance's existing private volume. It is not the agent's execution identity.
- `/workspace` retains its original private local persistent claim. Complete HOME/session state is mounted from `.legacy-home-v2` on that claim; it survives replacement directly. It is not a new CIFS migration, shared workspace or backup.
- Authentication uses a separate container/PID namespace and private `dsh-legacy-auth-user2` / `dsh-legacy-auth-user3` PVC. Execution never mounts this PVC or its seed Secret. Loopback connects the authenticated proxy to DSH; network policy blocks peer bypass and permits the ingress controller.
- Password records use scrypt N=32768/r=8/p=1, random salt, constant-time comparison, bounded verification concurrency and atomic mode-0600 persistence. An initial Secret seeds only an absent store. Password changes persist without being reset on restart.
- By explicit owner decision, current passwords stay unchanged until their owners change them privately through the existing password-change flow. No operator reset or automatic rotation is scheduled. Owners must not disclose new passwords in chat or reports. Known/default-password exposure remains until owners act; a hash does not make a known password safe. Kubernetes Secrets require protected RBAC and cluster encryption/backup policy; base64 is not encryption.

## Environments and audit

Legacy DSH2/DSH3 are explicitly Internet-only. Their login page disables the No Internet choice. Main private No Internet and Internet pairs are unchanged. Required internal inference, KDC and Livy destinations remain allowed; no datalake rights were added or reduced.

A third, operator-controlled audit exporter reads only the protected authentication audit subdirectory. It writes a sanitized recent-event projection to its own `dsh-admin-audit/legacy/legacy-dsh2` or `legacy-dsh3` central folder. It does not mount account records or the user's workspace. It shares the legacy pod network; it is not a separately firewalled environment.

The main admin dashboard merges recent main/legacy events and displays projection freshness. The main session count does not include legacy sessions. Projections contain time/event/user/environment only, refresh approximately every 30 seconds and retain at most 1000 recent entries; full source archives stay at source. This is not an immutable SIEM or complete command log. No passwords, tickets, prompts or command bodies are projected.

## Actual acceptance and limits

Both owner logins, history RPCs, logout revocation, two peer-login denials and real terminal WebSocket commands passed. Execution returned UID 10001 and could not access the protected account path or the obsolete workspace account file. Two durable markers per instance survived actual pod replacement. DSH2's nine session files (195386 bytes) and DSH3's one session file (14137 bytes) remained byte-identical by aggregate SHA-256. The tests list histories; they do not resume every old tool interaction.

Main password change/old-password denial, failed login, unmapped-runtime denial and oversized input rejection passed using a temporary synthetic identity, which was removed. Earlier full-account migration checks verified original main login routing and admin/owner separation. The latest merged admin API/DOM was tested in a local fixture; its exact source, live central projections and deployed reader were checked separately. Those are distinct forms of evidence.

Fresh connectivity checks cover a synthetic inference response and unauthenticated Livy reachability, not a new authenticated Spark job or source-data authorization. Remote Spark's public egress remains the previously accepted exposure. Preserving AD permissions does not establish sandbox-only access or read-only source rights.

## Safe rollout, rollback and lessons

1. Read back and snapshot the existing specification privately; never publish credential-bearing old command/env values. Original credential-bearing snapshots were sealed with Windows CurrentUser DPAPI and independently decoded for byte comparison before unencrypted copies were removed.
2. Stop the single writer before fingerprinting/copying complete HOME state. Compare original/copy session bytes before changing mounts. Retain the original generation and checkpoint; do not overwrite newer work with an old copy during rollback.
3. Replace one legacy instance at a time. Test actual owner login, terminal, histories, persistence and account-store separation before proceeding. Main execution and model pods need no restart for this change.
4. On failure restore the prior coherent specification. A pre-hash authentication source is not compatible with hashed records: retain the matching helper/source, or perform an explicit private store rollback. Never blindly apply old bootstrap YAML to a live installation.
5. Keep protected seed/auth Secrets and PVCs backed up under operator policy. Current Deployment YAML references immutable source ConfigMaps and protected resources; it is an accepted existing-install snapshot, not a self-contained fresh install.

Observed corrections retained for future maintenance:

- A Windows default-codepage error interrupted verification. Explicit UTF-8 was required; the failure was not treated as a passing product test.
- Pod `fsGroup` widened a strict credential file from 0600 to 0660 and DSH refused startup. Removing `fsGroup`, using bounded explicit ownership, and restoring mode 0600 resolved it. Do not reintroduce broad group-mode mutation.
- A separate audit Job could not publish the same TopoLVM/XFS auth volume read-only while the owner mounted it read/write. A narrowly mounted exporter in the same pod uses one CSI publication with a read-only audit subpath. Failed standalone jobs/policies were removed; the tracked source no longer deploys that design.
- An early legacy probe reported account count from its supplied test fixture, not the active store. The corrected final probe reads the actual store and confirms one active owner and no guest. Earlier records are preserved as historical harness output.

## Remaining decisions

The password policy is decided: preserve current passwords until owners change them privately. Owner-performed changes remain outstanding; this is not a pending request for operator rotation approval. Retirement of historical credential copies remains a separate operator task. Corporate identity/MFA/recovery, storage-server ACL/recovery policy, immutable audit retention, browser handling/DLP, remote-job correlation and remote Spark egress are separate controls. The risk report describes each at its relevant boundary; no additional data access is authorized.
