# Per-user execution isolation and the original environment design

## Why two environments

The user asked for Internet Off by default and an Internet environment that can obtain libraries for the offline environment. The later clarification was that shared storage was intended to supply dependencies, not to expose protected working data. The resulting design separates writable projects, chat sessions, attachments, runtime state and launch tokens. Internet writes candidate dependencies into incoming storage; an operator reviews provenance and security results and approves hashes; a promotion job publishes approved artifacts; No Internet mounts the approved cache read-only. Hash matching establishes artifact integrity, not package safety by itself.

The two environments share the authentication gateway and internal model service. They do not share protected workspaces or live history. Switching environment creates a new login session, without automatically copying data or conversation history.

## Restricted egress versus air gap

No Internet blocks public outbound connectivity at the pod network boundary. It still uses DNS, the authenticated gateway, internal inference and storage. It is network-connected and must be assessed for indirect leakage through allowed services, DNS forwarding, application responses, and operator transfers. Its purpose is to constrain generated code and tools while retaining interactive service.

A strict air gap removes live network paths to external networks. Internal services can exist inside that disconnected boundary, but a shared service with unrestricted external connectivity needs an independently reviewed boundary or must be brought inside the disconnected zone. Merely using an internal hostname does not establish an air gap. Controlled offline transfer can supply packages to an air-gapped platform. The current DSH design is restricted egress, not a strict air gap.

## User isolation extension

Each approved identity receives one Secure runtime and one Internet runtime. Each runtime has its own pod, Service, workspace PVC, state/history PVC, launch-token PVC and, for Internet, incoming-package PVC. Only approved packages are shared read-only across Secure runtimes. Internal LiteLLM/GPU inference and gateway identity administration remain shared services.

`scripts/generate_user_runtimes.py` generates reviewable manifests and an administrator-owned routing ConfigMap. It does not apply them, create identities, or copy data. `DSH_USER_TARGETS_FILE` activates identity-specific routing in the gateway. The authenticated identity and environment select a fixed Service and token file. Request parameters cannot supply a backend. Missing identity/environment mappings fail closed, and self-registration is denied while this mode is active. Existing HTTP, WebSocket, terminal and application proxy paths use that same target.

Runtime pods retain the existing restricted/Internet policy labels and gateway-only ingress rule, run non-root with dropped capabilities, use RuntimeDefault seccomp, and do not receive Kubernetes service-account credentials. Incoming package approval must explicitly select the requesting user's incoming PVC. The existing shared promotion job must not be assumed to consume these new private incoming PVCs automatically.

## Preserve the existing central storage requirement

The current generator allocates local workspace PVCs and therefore does not yet implement the corrected mounted-DA_WORKSPACE design. Do not deploy it as a complete storage solution. The [raw-transcript review](DA_WORKSPACE_DESIGN_REVIEW_20261015.md) confirms that abandoning the share was not requested. Private runtimes must use bounded environment/user subpaths on the mounted central workspace, retain non-root operation and central durable history, and keep Internet from protected paths. The non-root CIFS ownership mapping has passed an isolated live test. Restoring the existing mount is separate from redistributing historical data or granting new RDT access.

## Rollout and evidence boundary

RDT snapshot option: `--rdt-source-pvc APPROVED_SNAPSHOT_PVC --rdt-approval-ref OWNER_APPROVAL_REFERENCE` adds `/data/rdt` read-only to Secure runtimes only. Both options are required together. The PVC must already contain only the approved snapshot; the generator cannot determine data scope or grant database permissions. Public registration now defaults to disabled even before isolated routing is enabled.

1. Confirm named pilot identities and provision their accounts administratively. Build an immutable runtime image containing the new gateway code.
2. Generate manifests using `python scripts/generate_user_runtimes.py --users alice bob --image REGISTRY/IMAGE@sha256:DIGEST --output candidate.yaml` (requires PyYAML). These names are examples only.
3. Review image digest, storage quotas/capacity and existing NetworkPolicies. The existing gateway Service, authentication PVC, approved package PVC and egress policies are prerequisites; the generator does not duplicate them.
4. Provision dedicated runtimes before routing users to them. Establish ownership of legacy files/history first. Never clone the entire shared history store into every identity. Preserve legacy volumes and the gateway manifest for rollback.
5. Verify each new runtime is healthy, its token exists and the routing map matches its Service. Review the generated gateway token mounts before cutover. Updating the ConfigMap requires a gateway restart because routing is loaded at startup.
6. Test A-to-B file/session/report/attachment reads and writes through HTTP, WebSocket, terminal and tools; they must fail. Verify default No Internet and denied external traffic for every Secure runtime, Internet download, approved-package installation, logout, persistence and inference.
7. Only after these checks should legacy shared pool access be retired. Existing sessions remain on the old gateway until cutover and will require reauthentication.

Source tests cover identity routing, spoofed URL resistance, missing-route denial, registration denial, session stickiness and generated volume/Service boundaries. They do not establish deployed per-user isolation, migrate history, or prove RDT data authorization. Production was read back with the existing shared Secure/Internet deployments; this extension has not been deployed.

Dedicated pods provide a stronger process/storage boundary, but share the node kernel and inference service. They are not VMs or separate physical systems. RDT still requires its own limited read-only source identity/view and separate writable results location.
