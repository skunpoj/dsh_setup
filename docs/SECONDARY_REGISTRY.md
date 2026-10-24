# Optional persistent secondary registry

This package makes the secondary registry reproducible from repository source. It does not replace the primary registry automatically. The default DSH build pipeline remains on its configured primary connection; use the opt-in CI template only with separately approved registry connections. No application deployment, watcher operation or historical replay is included.

## Files and boundaries

- scripts/secondary_registry/render.cjs: pure Kubernetes List renderer, immutable source/config ConfigMaps, two bounded non-root Deployments, dedicated PVC, Services, selected-controller-only NetworkPolicies and verified HTTPS Ingress.
- scripts/secondary_registry/registry_*.js: standalone token runtime, RS256 60-second tokens, exact repository/action grants, machine credential revocation checks and optional native bridge. The supplied renderer enables machine-only mode; it never mounts DSH accounts or enables human login.
- scripts/secondary_registry/promote.cjs: remote-only existing-image promotion. It pulls an immutable source, checks the qualified config digest and ordered layer hashes, pushes one unique candidate tag, pulls the resulting immutable digest and checks content again. It never builds or starts a container, deploys, deletes or automatically retries.
- ci/secondary-registry.yml: opt-in Azure remote-builder template using protected Docker service connections. Do not run this on a personal laptop. Use a disposable approved agent credential store and preserve bounded protected diagnostics if a failure occurs.
- .github/workflows/secondary-registry.yml: synthetic Linux tests only. No registry credentials, cluster access, model calls or real accounts.

## Provisioned prerequisites

Supply a dedicated Test namespace ending in -test, an owned prefix ending in -test, observed ingress-controller labels/peer IPs, exact observed edge source /32 or /128 addresses, approved storage capacity/class, reachable DNS, ingress class and digest-pinned runtime images. A shared proxy address does not uniquely identify a builder; machine authentication and exact scopes are still required. NetworkPolicy must actually be enforced by the cluster CNI.

The renderer deliberately creates no Namespace, Secret, RBAC or account. Provision these through an approved protected operator route before applying the reviewed manifest:

| Reference | Required protected content |
|---|---|
| edgeTlsSecret | Valid edge TLS certificate/key; referenced only by Ingress |
| backendTlsSecret | Separate TLS key and certificate chain with registry-host SAN |
| backendTrustSecret | ca.crt used by ingress to verify the backend |
| signingSecret | key.pem, RSA signing private key |
| publicSigningSecret | rootcertbundle.pem, signing certificate matching the private key |
| machineSecret | machine-principals.json and independent registry-http-secret |

Use fresh, random machine secrets of at least 32 characters. Store only their SHA256 hashes server-side. Never copy DSH administrator passwords, a Production TLS private key or directory credentials. A server principal has enabled=true, a random 32..128 lowercase-hex rotationStamp, a 64-hex secretSha256 and grants such as {"team/app":["pull"]}. Identity names follow robot~name. Give the publisher pull,push and the separate Test-node identity pull only on one reviewed repository. No wildcard, delete or catalog permission. Deliver client credentials through protected stores, not Git, logs, review artifacts or this config.

Key/certificate creation and rotation are protected operator actions, not implicit installation side effects. Recheck validity, chain, SAN, issuer, trusted-peer observations and capacity before applying. The readBounded runtime expects directly mounted regular subPath files for protected inputs. ConfigMaps and generated manifests contain no private key or password.

## Render and install on an approved remote operator

Copy config.example.json to the ignored scripts/secondary_registry/config.local.json and replace every example infrastructure value with reviewed values. The example is a synthetic render fixture, not a usable deployment profile.

~~~sh
node scripts/secondary_registry/render.cjs scripts/secondary_registry/config.local.json NEW-registry-review.json
~~~

Review every object and verify referenced Secrets/namespace exist without exporting their values. The renderer writes with exclusive creation and does not contact Kubernetes. Compare names against the live inventory, reject collisions with existing resources, obtain a finite resource window, and create only the reviewed new objects through the approved cluster operator. Do not apply this fresh-install output over an existing operational registry. Existing installations require a separately reviewed migration: compare source/config hashes, protect the original PVC, preserve old image/config names and rollback receipts, and change nothing until that plan is authorized. No wholesale live migration is required merely to adopt these source files.

The storage uses ReadWriteOnce and Recreate; expect registry/token unavailability during replacements. TCP readiness shows a listener, not correct authentication or preserved content. Test client DNS, TLS and byte-level pull before use. Install public CA trust only for the exact registry on approved builders/nodes when required. Never use insecure-registry or disable certificate validation.

## CI image qualification and promotion

Provide an independently reviewed JSON qualification file with exactly sourceRef (source registry/repository@sha256 manifest), targetRef (secondary registry/repository:candidate-UNIQUE), configDigest (sha256 image-config identity) and layers (ordered sha256 diffIDs). These must come from the original successful qualification, not from whatever image happens to be present now. Bind its source commit, source-file map and qualification receipt in the release ledger. Equal config/layers establish image-content equality; source-code and behavioral qualification remain separate requirements.

Use ci/secondary-registry.yml from an approved remote Linux job with both protected service-connection parameters, qualificationFile and registrySourceRoot. The helper does not fetch Kubernetes Secrets or create permissions. Never use the public template to broaden an existing operator grant. Existing protected memory-only CI credential helpers may remain in use; do not replace them with plaintext Docker config files. Docker@2 connections use the remote agent's approved credential store, so run on an isolated job/agent and verify logout/credential-store cleanup. A failed job may leave an uploaded candidate/tag or partial upload; preserve receipts and inspect it before any explicit retry. No automatic fallback during an outage.

The immutableRef receipt is the only deployment reference to promote. Tags are discovery aids. Pull back and validate expected config/layers again on the target Test node before deployment; a builder pull can be satisfied from its cache and does not establish cold node delivery. Preserve the previous application digest, matching overlays/configuration, sessions/storage and recovery dependencies.

## Required acceptance and recovery

1. Anonymous pull/push denied; wrong secret, wrong audience/repository, disabled/rotated principal, wildcard/delete/catalog scopes refused. A pull-only identity cannot push.
2. Trusted HTTPS push then independent immutable pull; compare manifest/config/ordered layers and tiny fixture bytes. Preserve actual returned fields and timestamps.
3. Confirm the Test node can pull the exact digest under its own pull-only credential; do not infer this from a CI success badge.
4. Under a separate maintenance window, replace only the registry Pod and verify the original PVC UID/data and immutable pull bytes survive. Token/config replacement must retain compatible signing keys and registry-http-secret for active uploads.
5. Back up registry data using a version-supported consistent snapshot/quiescence procedure. Back up config/source identities and protected credentials separately to approved encrypted storage. Restore into a disposable isolated registry, verify manifest/config/layer bytes and permission denial, and preserve restore evidence. PVC persistence is not backup.
6. Before a candidate cutover, qualify candidate and rollback immutable images on the intended Test runtime. Verify actual running digest/code/features and preserved state. No Production or historical dispatch is part of this package.

Rollback changes only the owned new registry workloads/routes using recorded original names/UIDs/config/image digests. Never delete the PVC, shared ingress, DSH auth store or application state as a rollback shortcut. Keep the previous registry/source or primary connection available until acceptance passes. Disabling a machine principal prevents new tokens; existing tokens expire within 60 seconds. SubPath mounted immutable Secret changes require an authorized new reference/workload rollout; do not promise hot rotation.

Deletion and garbage collection are disabled by default. Do not implement latest-only retention until all active workloads, rollback references, multi-architecture manifests and external evidence dependencies have been inventoried. Use a separate reviewed version-supported maintenance window, tested backup/restore and reachability verification; deleting one tag is not proof blobs are reclaimable. Never run broad prune, PVC deletion or registry garbage collection from CI.

## Reproduce tests on remote Linux CI

~~~sh
DSH_NATIVE_SOURCE_ROOT="$PWD/scripts" DSH_IDENTITY_MODULE="$PWD/scripts/identity_auth.js" DSH_TEST_OPENSSL=/usr/bin/openssl node --test scripts/secondary_registry/test_*.cjs
~~~

Native-bridge tests use disposable synthetic account files only. No institutional account store or directory is read. If the optional native modules are unavailable, those tests skip; the machine-only runtime/TLS tests must still pass. Passing these tests is source verification, not live endpoint, restart, backup/restore, node-pull or Production acceptance.


## Automatic build scope and explicit CI intent

Registry source has a dedicated synthetic workflow. Institutional CI should exclude this package, its opt-in promotion template and registry-only runbooks from application-image triggers while retaining all application, ordinary test, dependency and pipeline changes. The build-intent.sh helper honors explicit standard [skip ci] / [ci skip] / Azure skip markers before Docker login, build, verification or push; ordinary commits return true. This also protects direct compare-and-swap ref updates where server-side skip detection may not occur. It never treats a failed image verification as success. Run test_build_intent.sh on remote Linux; an unreadable or oversized message fails the guard instead of allowing a build. No global disabling of application CI or collision/authentication checks is included.
