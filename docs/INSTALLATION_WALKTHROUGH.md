## How to install DSH

This walkthrough follows the repository's actual build, manifest-generation and inference-rendering interfaces. Run commands from the repository root in a POSIX operator shell. Windows operators can use WSL; Python-only generation also works in PowerShell. The recorded deployment and performance results appear separately under **What is deployed** and **Qualification results**.

### 1 Choose the deployment target and collect inputs

Use a new test namespace for a new installation. For an existing installation, preserve its current namespace, claims, account store and owner mapping; do not run initial provisioning over live routing. Never apply the entire `k8s` directory: it includes historical deployments and site-specific examples.

| Input | Operator supplies | Used by |
|---|---|---|
| Cluster access | Approved kubeconfig/context, policy-enforcing CNI, GPU device plugin, ingress and trusted TLS | Kubernetes deployment and acceptance |
| GPU capacity | Existing four-GPU node, compatible driver/runtime and sufficient shared memory | Model workload |
| Model storage | Bound model PVC and approved checkpoint staged at `/models/approved` | Portable model renderer |
| Central storage | SMB CSI driver, private share credentials, share location, UID/GID mapping and ACLs | Private No Internet projects and durable histories |
| Other storage | StorageClass, auth-state claim, per-runtime state/token claims, incoming/approved package claims | Gateway and private environments |
| Database | Running PostgreSQL service, persistent storage, backup policy and private connection URL | LiteLLM key management |
| Images | Built DSH application digest, qualified LiteLLM digest and pinned model image | Three distinct workloads; the DSH image is not the model image |
| Network | Gateway hostname/TLS, filtered resolver, cluster domain and approved internal destinations | Routing, Host/Origin checks and destination policies |
| Identities | Named DSH users, roles, environment permissions and restricted inference credentials | Private routes and authentication |

Keep values in an operator-only directory outside the checkout. The public examples intentionally contain no usable site credentials. A required value is an installation input, not a value the renderer discovers automatically.

```sh
git clone https://github.com/skunpoj/dsh_setup.git
cd dsh_setup
git rev-parse HEAD
python -m venv .venv
. .venv/bin/activate
python -m pip install PyYAML
kubectl config current-context
kubectl get nodes
kubectl get storageclass
```

Record the selected source commit and inspect the context before any write. Install Python packages on the operator workstation, not by enabling Internet on a No Internet runtime. Use an approved local package cache where operator Internet is unavailable.

### 2 Build and inspect the application image

The Dockerfile packages DSH, Claude Code, TrueForge, terminal and Kerberos tooling plus reviewed overlays. Read its pinned build arguments before changing versions. The checked-in Azure pipeline is a site-specific example; configure your own registry connection, repository and agent pool rather than copying its private registry settings.

```sh
export DSH_IMAGE_TAG='registry.example.net/ai/dsh-runtime:reviewed-build'
docker build --pull -t "$DSH_IMAGE_TAG" .
docker run --rm --entrypoint node -w /opt/dsh "$DSH_IMAGE_TAG" tests/test_user_isolation_routing.js
docker run --rm --entrypoint node -w /opt/dsh "$DSH_IMAGE_TAG" tests/test_auth_proxy_internet.js
docker run --rm --entrypoint node -w /opt/dsh "$DSH_IMAGE_TAG" tests/test_admin_users.js
docker push "$DSH_IMAGE_TAG"
docker pull "$DSH_IMAGE_TAG"
docker image inspect "$DSH_IMAGE_TAG" --format '{{json .RepoDigests}}'
```

Select the registry digest from the final output and set `DSH_IMAGE` to that complete `registry/repository@sha256:…` reference. Check installed client versions and patch checks inside this image. A successful build alone is not a login, persistence or network test. Stage the image into the target registry before restricting runtime egress.

### 3 Prepare storage, database and Secrets

Create the target namespace and provision its database and storage through the site's supported deployment tooling. Configure PostgreSQL service labels and the destination policy together: the portable renderer expects the database pod label `app: llm-database` and port 5432. Supply these inference Secrets through the approved secret manager:

| Secret | Required keys |
|---|---|
| `credentialSecret` from the settings JSON | `LITELLM_MASTER_KEY`, `INTERNAL_ROUTE_KEY` |
| `databaseSecret` from the settings JSON | `DATABASE_URL` |
| Each DSH inference-client Secret | `litellm-api-key` containing a model-only client key |

Keep the master key out of execution-worker mounts. Do not print Secret YAML, put credentials in command arguments or store them in the repository. PostgreSQL installation, schema initialization/migration and account-key issuance are operator steps; `gpu-stack/render.py` does not perform them.

For central storage, adapt a private copy of `k8s/dsh-da-workspace.yaml`: replace the share, volume handle, Secret reference and namespace; retain UID/GID 10001 only if it matches the chosen image. Verify non-root create, flush and reopen against an isolated test directory. Configure server ACLs as well as client mount modes. Keep the original share mounted; do not replace it with a local volume to bypass a permission error.

### 4 Render shared inference before applying it

```sh
export PRIVATE_DIR='/private/dsh-install'
mkdir -p "$PRIVATE_DIR"
chmod 700 "$PRIVATE_DIR"
cp gpu-stack/settings.example.json "$PRIVATE_DIR/inference-settings.json"
# Edit the private JSON with the approved namespace, existing PVC,
# gateway image digest and existing Secret names from steps 1–3.
python gpu-stack/render.py --settings "$PRIVATE_DIR/inference-settings.json" --output "$PRIVATE_DIR/inference-candidate.yaml"
```

The renderer creates model/gateway workloads, Services, immutable source ConfigMaps and their network policies. It does not create the namespace, model PVC, weights, PostgreSQL or Secrets. Its generic DNS rule is not the platform's filtered-DNS implementation. Review service names, peer labels and source hashes before connecting DSH.

```sh
export INFERENCE_NS='ai-workspace'
kubectl -n "$INFERENCE_NS" apply --dry-run=server -f "$PRIVATE_DIR/inference-candidate.yaml"
kubectl -n "$INFERENCE_NS" diff -f "$PRIVATE_DIR/inference-candidate.yaml"
# kubectl diff returns 1 when it finds changes; inspect them.
kubectl -n "$INFERENCE_NS" apply -f "$PRIVATE_DIR/inference-candidate.yaml"
kubectl -n "$INFERENCE_NS" rollout status deployment/local-model --timeout=2100s
kubectl -n "$INFERENCE_NS" rollout status deployment/local-inference --timeout=300s
```

Apply only to the reviewed target. Read back image IDs, arguments, mounted source and actual answer content. The first model start can be lengthy. Test authenticated inference using a restricted key without exposing it. Model port 8000 must remain private to the gateway; the final-wire preparation listener is loopback-only. Keep the 1M total budget, 8,192 output ceiling, 256 reserve and one-long-request admission aligned across clients and proxy.

### 5 Generate private user/environment candidates

```sh
python scripts/generate_user_runtimes.py --help
python scripts/generate_user_runtimes.py --users pilot-a pilot-b --image "$DSH_IMAGE" --output "$PRIVATE_DIR/private-users.raw.yaml"
```

This writes Deployments, per-runtime PVCs, private Services, routing and gateway-source ConfigMaps, and the gateway Deployment. It does not apply them, create login accounts, issue inference keys, initialize central subdirectories or migrate histories. Unlike the inference renderer, it can overwrite its output path; use a new filename for each review.

The current application generator is **site-bound**: it emits namespace `llm`, `.llm.svc.cluster.local` routes, the template's DNS configuration and existing central/package claim references. It does not accept a namespace option. Before using another site, adapt a private copy of the generated YAML and referenced configuration together. Do not assume `kubectl -n` rewrites explicit namespaces or route hostnames. Keep an untouched generated file and a separate reviewed `private-users.site.yaml`.

For each candidate, inspect every PVC, Secret and ConfigMap reference. Provision missing claims and per-user inference Secrets first; prepare only that user's central subdirectories. Keep Secure and Internet project/history/credential mounts separate. The central claim is shared infrastructure, but each worker mounts only its scoped subpaths. Verify no broad parent exposes peer directories. The generator does not contain the gateway Service, ingress or all supporting policy/configuration resources; supply their reviewed private-site versions separately.

The existing `provision_inference_client.py` targets namespace `llm` and deployment `litellm`; it is not directly compatible with the portable `local-inference` names. Adapt that integration explicitly, or issue restricted keys through the target LiteLLM administrator interface. Likewise, `rollout_private_routing.py` is an existing-site migration utility with ownership/evidence gates, not a new-cluster installer.

### 6 Apply supporting controls, then start private workloads

Prepare a private supporting bundle containing the filtered DNS configuration/service, storage and profile ConfigMaps, gateway Service, TLS ingress, environment network policies and package-promotion resources. Use the corresponding `k8s` files as reference inputs, not a blanket apply list. Replace all site destinations and align their labels with the generated workloads. Approved package storage is read-only to No Internet; only controlled promotion writes to it.

```sh
export APP_NS='llm'
kubectl -n "$APP_NS" apply --dry-run=server -f "$PRIVATE_DIR/supporting.site.yaml"
kubectl -n "$APP_NS" apply --dry-run=server -f "$PRIVATE_DIR/private-users.site.yaml"
kubectl -n "$APP_NS" diff -f "$PRIVATE_DIR/supporting.site.yaml"
kubectl -n "$APP_NS" diff -f "$PRIVATE_DIR/private-users.site.yaml"
# After reviewing both diffs, install supporting controls first.
kubectl -n "$APP_NS" apply -f "$PRIVATE_DIR/supporting.site.yaml"
kubectl -n "$APP_NS" apply -f "$PRIVATE_DIR/private-users.site.yaml"
kubectl -n "$APP_NS" get deployments,pods,pvc,services,networkpolicies
```

The two `.site.yaml` bundles are operator-prepared outputs, not files supplied by this repository. Resolve every referenced resource before this step. Configure the gateway's trusted host and TLS, default No Internet selection, server-side private routing and disabled registration. Grant Internet separately per named account. Seed the initial administrator through the protected account-store procedure; do not introduce a factory password. Use Admin → User management for additional already-provisioned private runtimes.

### 7 Verify the installed behavior before handover

| Check | Required result |
|---|---|
| Login and account roles | Correct login works; incorrect login, forged roles and ordinary-user admin calls fail; logout invalidates access |
| Environment selection | No Internet is default; unauthorized Internet selection is refused by the server |
| Isolation | Two synthetic users cannot read each other's histories, files, attachments or terminal sessions |
| Network | Public-domain and direct-IP requests fail in No Internet; permitted inference works; Internet operates only in its separate environment |
| Dependency transfer | Internet writes incoming artifacts; reviewed promotion verifies hashes; No Internet can read approved artifacts but cannot alter them |
| Persistence | A disposable file and conversation survive controlled runtime replacement with identical content; existing histories retain IDs and bytes |
| Inference | Native DSH gives correct persisted answers at ordinary, 256K, 512K and near-1M sizes, with real tool continuation and short requests overlapping long work |
| Admission and recovery | A second long request obeys the bounded queue; further waiters are refused; cancellation releases admission; short work continues |
| Administration | Authorized overview shows correctly scoped activity/capacity; other users cannot obtain admin data |

Start with synthetic content. Use actual browser login, HTTP/WebSocket terminal interaction and saved conversation readback; a rollout status does not replace these checks. Record first-text latency, preparation time and streaming output rate separately. Remote submitted jobs retain the remote platform's network and AD permission boundaries.

### 8 Roll back without losing newer work

Before upgrading an existing site, retain the exact old Deployment specs, immutable ConfigMaps/image digests, routing/account configuration and a private history/file fingerprint. Keep credentials in protected recovery storage. Replace one private runtime at a time and repeat the affected behavior checks. On regression restore its reviewed old image/configuration and route; do not delete PVCs or overwrite newer histories with an old snapshot. Stop the writer and reconcile newer central writes before changing storage mounts. Model changes on the single shared GPU node interrupt inference; retain the last qualified model profile for that separate rollback.

### Installation coverage

The commands above expose the actual installation sequence and remaining operator inputs. The portable inference renderer and private-runtime generator can be exercised offline. A fresh-cluster install, site bundle, database migration and initial administrator bootstrap still require the target site's supported tooling and acceptance. They are not a single copy-and-run installer. Existing deployment qualification is documented separately and does not establish a fresh-site installation test.
