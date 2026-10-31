# OpenShell runtime qualification

The integration is not a deployed OpenShell service. Its 25 product acceptance gates remain unrun. A kernel capability or Kubernetes network test must not be substituted for those gates.

A bounded disposable CPU-only preflight observed Landlock ABI 6 and seccomp user-notification support under the container security profile. A single receiver was reachable by the permitted probe before and after the negative tests. Independent ingress-denied and egress-denied probes could not reach that receiver. The temporary namespace was removed and its absence was read back. No existing workspace was modified, no GPU resource was requested and the probes requested no model calls.

This establishes prerequisites only. It does not show that OpenShell applied Landlock, admitted the effective policy, authenticated a DSH owner, contained every tool/process path, preserved a sandbox across replacement, or correctly injected a synthetic provider credential.

The remaining deployment inputs and work are:

1. Qualify immutable gateway, supervisor, sandbox-runtime and derivative DSH worker images. A chart digest alone is not a workload-image digest.
2. Establish a dedicated namespace, bounded resources/storage and controller permissions. Do not install broad cluster roles as an incidental effect of a test release.
3. Configure verified TLS and an approved identity issuer, audience and operator/user roles. Example domains, empty issuer values and all-zero image digests must fail admission.
4. Bind HTTP and WebSocket routing to the authenticated DSH subject and selected environment. Operator labels alone are not an owner authorization boundary. Test revocation and forged peer routes.
5. Admit a separate synthetic provider/broker profile with exact methods and paths. Do not silently broaden the deny-network baseline or mount an operator token in the worker.
6. Run all 25 product gates against the actual installed images, policy and identities. Include independent positive controls, persistence, cancellation, cleanup and rollback. Save unrun or failed results explicitly.

Existing DSH execution isolation remains a separate deployed control. This prerequisite result does not replace it or declare OpenShell production-ready. OAuth application registration and Kerberos ticket acquisition are also separate integrations; no provider registration or AD permissions were changed by the preflight.
