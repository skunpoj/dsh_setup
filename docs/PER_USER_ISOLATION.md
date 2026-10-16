# Per-user execution isolation and the original environment design

**Ownership restored, 16 October 2026:** `thanatcc` now routes to its preserved No Internet and Internet runtimes. All 80 histories / 82 session files retain their recorded hash; all 82 working-directory records point to readable directories outside the masked paths. Admin routes to fresh private runtimes, retains dashboard/audit access, and is denied legacy-history reads through DSH. The owner runtime masks the private-user subtree, three reviewed credential-file aliases, and the routing/recovery directories. Infrastructure administrators remain trusted. See [live owner restoration](context-evidence/legacy-owner-restoration-live-20261016.json).

## Why two environments

The user asked for Internet Off by default and an Internet environment that can obtain libraries for the offline environment. The later clarification was that shared storage was intended to supply dependencies, not to expose protected working data. The resulting design separates writable projects, chat sessions, attachments, runtime state and launch tokens. Internet writes candidate dependencies into incoming storage; an operator reviews provenance and security results and approves hashes; a promotion job publishes approved artifacts; No Internet mounts the approved cache read-only. Hash matching establishes artifact integrity, not package safety by itself.

The two environments share the authentication gateway and internal model service. They do not share protected workspaces or live history. Switching environment creates a new login session, without automatically copying data or conversation history.

## Restricted egress versus air gap

No Internet blocks public outbound connectivity at the pod network boundary. It still uses DNS, the authenticated gateway, internal inference and storage. It is network-connected and must be assessed for indirect leakage through allowed services, DNS forwarding, application responses, and operator transfers. Its purpose is to constrain generated code and tools while retaining interactive service.

A strict air gap removes live network paths to external networks. Internal services can exist inside that disconnected boundary, but a shared service with unrestricted external connectivity needs an independently reviewed boundary or must be brought inside the disconnected zone. Merely using an internal hostname does not establish an air gap. Controlled offline transfer can supply packages to an air-gapped platform. The current DSH design is restricted egress, not a strict air gap.

## User isolation extension

Each approved identity receives one Secure runtime and one Internet runtime. Each runtime has its own pod, Service, state/history PVC, launch-token PVC and, for Internet, staging/incoming-package PVCs. Secure workspaces use distinct bind-mounted subpaths of the central DA_WORKSPACE claim. Only approved packages are shared read-only across Secure runtimes. Internal LiteLLM/GPU inference and gateway identity administration remain shared services.

`scripts/generate_user_runtimes.py` generates reviewable manifests and an administrator-owned routing ConfigMap. It does not apply them, create identities, or copy data. `DSH_USER_TARGETS_FILE` activates identity-specific routing in the gateway. The authenticated identity and environment select a fixed Service and token file. Request parameters cannot supply a backend. Missing identity/environment mappings fail closed, and self-registration is denied while this mode is active. Existing HTTP, WebSocket, terminal and application proxy paths use that same target.

Runtime pods retain the existing restricted/Internet policy labels and gateway-only ingress rule, run non-root with dropped capabilities, use RuntimeDefault seccomp, and do not receive Kubernetes service-account credentials. Incoming package approval must explicitly select the requesting user's incoming PVC. The existing shared promotion job must not be assumed to consume these new private incoming PVCs automatically.

## Preserve the existing central storage requirement

The generator now retains `dsh-da-workspace-secure` and assigns `dsh/private/<identity-hash>/secure` as the workspace subpath. It does not redistribute existing shared files/history. Administratively pre-create and verify those central directories before applying private runtimes; their main containers must never mount the share root. The shared Secure workspace was remounted and restart-tested at 21:32 ICT on 15 October. On 16 October, eight non-admin accounts were cut over to private runtimes in both environments; `thanatcc` now has legacy access and admin has a separate private runtime pair. See [actual correction evidence](context-evidence/central-workspace-live-20261015.json).

## Rollout and evidence boundary

Optional synthetic filesystem fixture: `--readonly-fixture-pvc APPROVED_FIXTURE --fixture-approval-ref REVIEW_REFERENCE` adds `/data/fixtures` read-only to Secure test runtimes. This is unrelated to real RDT, which uses user-specific Kerberos and existing datalake rights. Both fixture options are required together. No shared RDT service identity or universal read-only policy is provisioned. Public registration remains disabled.

1. Confirm named pilot identities and provision their accounts administratively. Build an immutable runtime image containing the new gateway code.
2. Generate manifests using `python scripts/generate_user_runtimes.py --users alice bob --image REGISTRY/IMAGE@sha256:DIGEST --output candidate.yaml` (requires PyYAML). These names are examples only.
3. Review image digest, storage quotas/capacity and existing NetworkPolicies. The existing gateway Service, authentication PVC, approved package PVC and egress policies are prerequisites; the generator does not duplicate them.
4. Provision dedicated runtimes before routing users to them. Establish ownership of legacy files/history first. Never clone the entire shared history store into every identity. Preserve legacy volumes and the gateway manifest for rollback.
5. Verify each new runtime is healthy, its token exists and the routing map matches its Service. Review the generated gateway token mounts before cutover. Updating the ConfigMap requires a gateway restart because routing is loaded at startup.
6. Test A-to-B file/session/report/attachment reads and writes through HTTP, WebSocket, terminal and tools; they must fail. Verify default No Internet and denied external traffic for every Secure runtime, Internet download, approved-package installation, logout, persistence and inference.
7. Only after these checks should legacy shared pool access be retired. Existing sessions remain on the old gateway until cutover and will require reauthentication.

Private-user routing is now deployed and tested for eight non-admin identities across both environments. The original two runtimes now route only to `thanatcc`, retaining 80 unchanged histories. Admin has a separate private runtime pair. Source and live evidence distinguish identity routing, spoofed-header denial, terminal/application access, persistence and inherited AD data authorization. Existing AD/datalake rights are preserved; local DSH login is not AD/SSO. See the current security report and private-runtime acceptance records for actual deployed evidence.

Dedicated pods provide a stronger process/storage boundary, but share the node kernel and inference service. They are not VMs or separate physical systems. Datalake authorization preserves each principal’s existing AD/Hive/HDFS permissions, per the user’s selected policy; universal read-only access is not imposed.
