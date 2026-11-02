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

## When OpenShell can become available

OpenShell can be enabled only after one exact candidate release passes all 25 live Test gates and its rollback check. The current acceptance count is **0/25**. Source tests, the CPU preflight, a successful image pull, Pod readiness or a successful model response do not increment this count.

There is no calendar completion date until the following admission inputs exist together:

- an immutable gateway, supervisor, sandbox-runtime and worker image set with exact source, package and image-digest provenance;
- a worker image that actually contains the reviewed OpenShell worker protocol implementation;
- a dedicated Test namespace with approved node placement, resource quota, storage, network policy, identity/audience configuration, expiry and cleanup ownership;
- a single Test operator, frozen gate matrix, saved predecessor rollback objects and independent readback access;
- separately authorized bounded model-backed tests for only the gates that genuinely require inference. No provider call is implied by the other gates.

The 25 gates are accepted as one release, but they cover distinct control families:

| Gate family | Required live evidence |
|---|---|
| Platform and policy admission | Kernel capability, hard-required refusal, CNI positive/negative controls and proof that no policy path was skipped |
| Identity and storage isolation | Authenticated owner binding, forged/cross-owner denial, read-only inputs, writable outputs and denial of unrelated paths |
| Process and escape containment | Traversal, symlink, file-descriptor, process-environment, socket, child-process, installer and tool-boundary probes |
| Network and credential containment | IPv4/IPv6, DNS, proxy, redirect and non-HTTP bypass denial; metadata/control-plane denial; exact approved broker/package paths; synthetic credential leak controls |
| Fail-closed lifecycle | Gateway/supervisor failure, no unrestricted fallback, exact descendant cancellation, logout/revocation, restart non-replay and worker-absence readback |
| User-facing behavior | Terminal streaming/resize/reconnect/interrupt/Unicode, notebook and file transfer, HTTP/WebSocket behavior, application audience controls and durable files/history |
| Model and audit integration | Mock inference stream, context and usage correlation, HTML remote-resource controls, correlated audit and secret redaction |
| Capacity and recovery | Paired resource measurements, owned rollback, drain, durable-data preservation and proof that unrelated watchers remain unchanged |

Availability is a release decision after the evidence packet shows **25/25 PASS**, the exact Test objects have been cleaned up, the known-working private-workspace backend remains healthy, and rollback can be executed by its recorded owner. Any failed, skipped, ambiguous or stale gate keeps OpenShell disabled. A first clean run is expected to require a dedicated multi-hour Test window; that is an execution estimate, not an acceptance promise.

## Worker-image live readback

A separate, disposable CPU-only image check pulled and ran the retained private
worker image on the assigned Test node. The actual output confirmed UID 10001 and absence of
`/usr/local/bin/dsh-openshell-worker`. Thus this historical image is pullable but
cannot execute the new native worker protocol. A successor immutable image is
required; this check does not establish source provenance or any of the 25
native runtime gates.

The probe used no service-account token, PVC, GPU or model endpoint. It ran with
deny-all network policy, restricted nonroot security context and a finite
deadline. The exact Pod, policy, quota and newly created namespace were deleted
with UID preconditions; namespace absence was read back. Receipts are retained
in `outputs/dsh-integration-review-20261101/completion-20261102/` outside the repo.
