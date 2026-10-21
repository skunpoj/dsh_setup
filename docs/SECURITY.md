# Three containment boundaries

## Prevent external leakage

No Internet runtime egress is limited to the non-forwarding-by-default filtered DNS relay and internal LiteLLM.
Internet runtimes have separate state/workspaces and may access public networks.
They cannot mount No Internet data. Model and database services deny outbound
traffic; LiteLLM can reach only DNS, the model and database. The final-wire guard
listens on loopback and is never exposed by a Service. Clients cannot bypass the
guard by directly reaching the backend when the CNI enforces the policies.

DNS, ingress and CNI behavior must be verified in your cluster. The supplied filtered resolver accepts only named platform services and the bounded private-runtime naming pattern in the authoritative cluster zone; unknown queries are refused locally, and client EDNS/extra sections are not forwarded. The cluster DNS service must not forward that private authoritative zone to public resolvers. This is restricted egress, not a physical air gap. Remote
execution systems are not configured: adding one requires controls where remote
code actually executes, not merely at the submitting pod.

## Prevent damage or excessive access

Each user/environment has its own non-root execution pod, state and workspace
claims, resource limits and model-only key. Runtime containers drop capabilities,
disable privilege escalation and have no Kubernetes API token. Trusted bounded
initializers prepare only their fresh private volumes; generated code does not
run as root. The inference/database services are separate trusted infrastructure.

Internet cannot install into No Internet. An operator reviews dependency source,
version and hash before promotion into the approved cache, mounted read-only by
No Internet. `container/promote_packages.py` accepts an explicitly approved hash
manifest and fails on symlinks, changed artifacts or conflicting destinations.
Run promotion as an operator-controlled Job with only one user's Incoming claim
read-only and the approved claim writable. Never give execution pods that write
mount or treat correctly hashed packages as automatically safe.

No corporate credentials or data privileges are included. A future data identity
must be separately authorized to the required source/result scope. Workspace
isolation does not make writable source data read-only. Quotas and backups limit
damage but do not prevent every destructive command within the user's own files.

## Keep results contained

The authenticated gateway binds identity to fixed server-side routing. Ordinary
users cannot select a peer backend or mount its files/history. The password store
and central access audit are mounted only by the gateway, not execution workers.
Each password uses a random salt and scrypt; accounts are provisioned privately,
without factory passwords or self-registration. Existing installations should
not reset owners' passwords without their approved process.

TLS, browser/file/report routes, logout and WebSockets require acceptance tests.
Access logs exclude password/prompt bodies and are not an immutable command
ledger. Administrators, the container host and storage operators remain trusted.
An authorized viewer can copy displayed content; endpoint controls are separate.

Do not commit generated manifests, kubeconfigs, API tokens, keytabs, transcripts,
staff details, real storage paths or deployment hostnames. Pattern scans must be
supplemented by source review and Git-history review before public publication.
