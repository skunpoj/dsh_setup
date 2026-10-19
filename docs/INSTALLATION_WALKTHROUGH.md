## How to install DSH

For the consolidated DSpark decisions, failed trials, memory corrections, preparation overhead and accepted measurements, see the [inference optimization experience record](INFERENCE_OPTIMIZATION_EXPERIENCE.html).

This walkthrough follows the repository's actual build, manifest-generation and inference-rendering interfaces. Run commands from the repository root in a POSIX operator shell. Windows operators can use WSL; Python-only generation also works in PowerShell. The recorded deployment and performance results appear separately under **What is deployed** and **Qualification results**.

### Installation sequence and completion gates

Follow steps 1–8 in order. Keep one private installation record with the source commit, chosen input values, rendered manifest hashes and acceptance results. Complete each gate before proceeding.

| Stage | Completion gate | Detailed reference |
|---|---|---|
| Prerequisites and images | Correct cluster; drivers/CSI/CNI available; image pulled by digest | Steps 1–2 below |
| Storage and database | Claims mounted with intended identity; weights readable; PostgreSQL initialized; Secret keys present | Step 3 and [storage guide](MULTI_TENANT_STORAGE_AND_PERSISTENCE.md) |
| Inference | Reviewed manifest; correct loaded checkpoint; authenticated correct answer; direct bypass denied | Step 4 and [portable GPU setup](../gpu-stack/README.md) |
| Private runtimes and gateway | All references resolved; private mounts/routes; login and roles accepted | Steps 5–6 below |
| Functional acceptance | Cross-user denial, persistence, terminal, network, tools and long/short inference checks pass | Step 7 and [LLM configuration/results](LLM_SETUP_AND_TEST_RESULTS.html) |
| Handover | Qualified configuration recorded; rollback preserves newer data | Step 8 below |

The portable GPU renderer and the site-bound DSH generator are two components of this sequence. Generating both files does not automatically join their service names, namespaces, DNS or credentials; the private site bundles must join those explicitly.

### 1 Choose the deployment target and collect inputs

Use **DeepSeek-V4.1-Flash-1017**, pinned to revision `1bae0e1088993b9b82de08f59de5be5a34e42170`, for the qualified DeepSeek setup. Follow the [checkpoint staging and integrity procedure](MODEL_UPDATE_1017.html) before starting inference. Stage the verified snapshot so `/models/approved` inside the model container resolves to that exact checkpoint; the portable template uses this generic mount path rather than downloading weights or selecting the newest release automatically. A readable `config.json` alone does not establish the checkpoint identity or complete shard integrity.

| Configuration scope | Installation setting |
|---|---|
| DeepSeek model, LiteLLM route and managed DSH profile | 1,048,576 total tokens; 8,192 maximum output; 256-token proxy reserve |
| DeepSeek inference optimization | DSpark block five; qualified 0.923 static fraction; eight active slots; 1,024-token prefill chunks/budget; 128 MiB score tiles |
| DeepSeek long-request admission | One expensive request above the 131,072-token input-plus-output threshold, plus one bounded waiter; this threshold is not a 128K context ceiling |
| Separate GLM and Qwen catalog/provider entries, when installed | Keep each model's own supported and verified limits; the DeepSeek update does not raise their limits or replace their weights |

Keep the stable DeepSeek client aliases pointing to the updated checkpoint. Do not change every catalog entry to 1M: aliases, actual checkpoint support and route budgets must agree for each model separately. Verify the loaded model path/revision and an actual answer after rollout. The application image, model weights and model-serving image are independent versions; updating the checkpoint does not upgrade the DSH package.

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

The Dockerfile packages DSH, Claude Code, TrueForge, Kilo CLI, terminal and Kerberos tooling plus reviewed overlays. Kilo is pinned with `KILO_VERSION=7.8.12`; its operator policy is installed into `/etc/kilo/kilo.json`. The [managed-client guide](MANAGED_CLIENT_SUPPORT.html) covers endpoint adaptation, private state and acceptance. Read its pinned build arguments before changing versions. The checked-in Azure pipeline is a site-specific example; configure your own registry connection, repository and agent pool rather than copying its private registry settings.

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

Before applying, run the offline reference check against all prepared bundles:

```sh
python scripts/check_installation_bundle.py \
  --manifest "$PRIVATE_DIR/inference-candidate.yaml" \
  --manifest "$PRIVATE_DIR/supporting.site.yaml" \
  --manifest "$PRIVATE_DIR/private-users.site.yaml"
```

Missing PVCs, Secrets, ConfigMaps, account references, ingress Services and unpinned container images are reported. Resolve each failure in the bundles. For a resource that already exists, verify its name and namespace separately and pass `--external Kind/namespace/name` for that resource. This is an explicit dependency declaration, not permission to assume a Secret or volume exists. Inspect required Secret key names without exposing their values. Never include credential values in the checker arguments or output.

The offline checker does not prove Secret key contents, PVC binding, correct subdirectories/ACLs, DNS resolution, network enforcement, database schema, registry access or application behavior. Server dry-run validates the cluster API/schema/admission path; Kubernetes can still accept a Deployment whose referenced resource is absent. Both checks and the following runtime tests are needed.

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

### Publish the on-site user manual

The floating User manual button opens `/manual/` on the same site. It opens the combined user manual, including practical tasks, environment/risk design, administration, installation, stress results and LLM/GPU setup. Its captioned guided tour provides play/pause and chapter controls. The platform reference, risk/features report and setup/test guide remain separate reference documents, not substitutes for the manual. Workload counts belong in the operator inventory.

Generate the combined guide after refreshing its platform, installation and test sources. Publish only reviewed public documentation, separately from user workspaces and account records:

```sh
node scripts/build_user_manual.mjs
python scripts/build_manual_bundle.py --output "$PRIVATE_DIR/manual-bundle"
python scripts/publish_manual_bundle.py --bundle "$PRIVATE_DIR/manual-bundle" --namespace "$APP_NS" --deployment dsh-environment-gateway
```

The publisher verifies every file hash and returns a versioned `manualDir` under `/auth/manuals/`. Set the gateway's `DSH_MANUAL_DIR` to that returned path in its reviewed Deployment. For an existing site, `rollout_admin_management.py --manual-dir` can combine that setting with a verified gateway-source update and rollback. Only the gateway reloads; execution runtimes and inference do not restart. Existing browser sessions may require sign-in again after that gateway reload.

Open the login page, follow User manual, verify the expected title/content and test its links and diagrams. The route accepts only catalogued documentation with matching hashes; it does not serve an arbitrary filesystem path. Public manual access does not grant access to user files, terminals, histories or admin routes. Keep prior versioned manual directories for rollback.

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

For each row, record the expected result, observed result and pass/fail. Stop handover if a required check fails; correct the configuration and rerun the affected check. For mounts, inspect the actual mounted source and read back saved file contents after restart. For inference, verify the model identifier, exact answer and saved assistant response, not just HTTP success. For packages, test both permitted installation from the approved cache and refusal to modify it. For networking, test from the execution process as well as the browser-facing gateway.

Start with synthetic content. Use actual browser login, HTTP/WebSocket terminal interaction and saved conversation readback; a rollout status does not replace these checks. Record first-text latency, preparation time and streaming output rate separately. Remote submitted jobs retain the remote platform's network and AD permission boundaries.

### 8 Roll back without losing newer work

Before upgrading an existing site, retain the exact old Deployment specs, immutable ConfigMaps/image digests, routing/account configuration and a private history/file fingerprint. Keep credentials in protected recovery storage. Replace one private runtime at a time and repeat the affected behavior checks. On regression restore its reviewed old image/configuration and route; do not delete PVCs or overwrite newer histories with an old snapshot. Stop the writer and reconcile newer central writes before changing storage mounts. Model changes on the single shared GPU node interrupt inference; retain the last qualified model profile for that separate rollback.

### Installation coverage

The commands above expose the actual installation sequence and remaining operator inputs. The portable inference renderer and private-runtime generator can be exercised offline. A fresh-cluster install, site bundle, database migration and initial administrator bootstrap still require the target site's supported tooling and acceptance. They are not a single copy-and-run installer. Existing deployment qualification is documented separately and does not establish a fresh-site installation test.
