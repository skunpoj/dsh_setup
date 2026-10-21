# Complete Kubernetes installation

## Prerequisites

- A separate Kubernetes environment with a working NVIDIA driver/device plugin
  and NetworkPolicy-enforcing CNI. The reference model profile uses one node with
  four H100-class GPUs, at least the requested host RAM, shared memory and model
  storage. GPU model/cache/workspace requirements vary; validate actual capacity.
- Dynamic RWO storage for private state/workspaces/database/model cache and RWX
  storage for routing tokens and approved packages. Supply your own CSI drivers.
  The model download job and model pod must use the same GPU-node selector so
  local-volume binding does not put weights on an incompatible node.
- `kubectl`, Python 3.11+, PyYAML and a container builder. Node 22 is used for local
  JavaScript tests. Configure an image registry with pull access from the cluster.
- An ingress controller, a DNS name you control and a trusted TLS certificate.
  The generated network policy must match the actual controller labels/network.
- Review the pinned model/package licenses and remote-code trust requirements.
  Download weights and build images before applying runtime Internet restrictions.

## 1 Build the runtime

```sh
docker build -t YOUR_REGISTRY/ai-workspace:reviewed .
docker push YOUR_REGISTRY/ai-workspace:reviewed
```

Obtain the pushed immutable digest from your registry/builder and place the
`YOUR_REGISTRY/ai-workspace@sha256:...` reference in local configuration. The
Dockerfile installs pinned DSH and managed-client versions, verifies upstream
patch contracts and checks the resulting installed profile. A changed contract
requires source review, not updating hashes until the build happens to pass.

## 2 Local configuration and rendering

```sh
python -m pip install -r requirements-dev.txt
cp config.example.yaml config.local.yaml
# Edit the ignored local file: namespace, storage classes, image digest,
# hostname, ingress settings, accounts and GPU-node selector.
python scripts/render_k8s.py --config config.local.yaml --output generated
```

Before rendering, create the selected namespace and allocate the filtered-DNS Service:

```sh
kubectl create namespace YOUR_NAMESPACE
kubectl -n YOUR_NAMESPACE apply -f templates/dns-service.yaml
kubectl -n YOUR_NAMESPACE get service filtered-dns -o jsonpath='{.spec.clusterIP}'
kubectl -n kube-system get service -l k8s-app=kube-dns -o jsonpath='{.items[0].spec.clusterIP}'
```

Put those two discovered addresses in ignored local configuration as
`filtered_dns_ip` and `cluster_dns_ip`. They are installation-specific, not public
example values. CoreDNS must be authoritative for your configured cluster domain;
verify no public fallthrough for that zone. Then run the renderer command above.
The renderer configures No Internet, gateway and LiteLLM DNS before policies are
applied; Internet runtimes keep ordinary cluster DNS. Bring the filtered resolver
up before waiting for the remaining shared services.

The example user names are synthetic. Choose provisioned identities locally;
there are no default passwords. Label your own selected GPU node to match the
configured selector. Do not put node hostnames, production addresses or accounts
into the public example. `generated/` is ignored and may contain your deployment
metadata, although it contains only Secret references, not Secret values.

## 3 Namespace, storage and protected Secrets

```sh
kubectl apply -f generated/namespace.yaml
kubectl apply -f generated/storage.yaml
python scripts/bootstrap_secrets.py --config config.local.yaml
```

The helper prompts privately for each initial account password, stores salted
scrypt records and generates separate random database/master/salt values. It
uses `kubectl create` and refuses an existing account or platform Secret. Do not
rerun it to reset passwords or rotate the LiteLLM salt: doing so can invalidate
stored encrypted credentials. Apply cluster Secret RBAC, encryption and backup
policy; Kubernetes base64 encoding is not encryption.

Create the configured TLS Secret through your approved certificate process. If
the model requires authentication, create optional `model-download` with key
`token` from a protected local file or Secret manager. Do not pass passwords or
tokens in shell command arguments, commit Secret YAML or save them in terminal
transcripts. The helpers do not export a master key for end users.

## 4 Download the pinned model first

```sh
kubectl apply -f generated/download.yaml
kubectl -n YOUR_NAMESPACE wait --for=condition=complete job/download-model --timeout=7200s
kubectl -n YOUR_NAMESPACE delete job download-model
```

The job downloads the pinned repository revision to `/models/model` on the model
claim; verify files/available capacity before continuing. Delete the completed
Job, not its PVC, to release the writer. Runtime model loading is offline.
There is no runtime fallback to a public model service.

## 5 Start core services and issue least-privilege client keys

```sh
kubectl apply -f generated/platform.yaml
kubectl -n YOUR_NAMESPACE rollout status deployment/filtered-dns --timeout=300s
kubectl -n YOUR_NAMESPACE rollout status deployment/database --timeout=300s
kubectl -n YOUR_NAMESPACE rollout status deployment/model --timeout=1800s
kubectl -n YOUR_NAMESPACE rollout status deployment/litellm --timeout=600s
kubectl -n YOUR_NAMESPACE rollout status deployment/gateway --timeout=300s
kubectl -n YOUR_NAMESPACE port-forward --address 127.0.0.1 service/litellm 14000:4000
```

In a second operator terminal:

```sh
python scripts/provision_clients.py --config config.local.yaml --port 14000
```

Then stop the operator-only forward. Each runtime initially waits for its own
inference Secret; it receives only a model-scoped virtual key, never the gateway
master key. Wait for all `user-*` Deployments and verify their actual behavior.
The gateway prepares separate routing-token subdirectories before these runtime
Secrets are issued. Keep one gateway/forwarder replica: long admission currently
uses a process-shared lock, not a distributed multi-replica lease.

## 6 TLS browser access and acceptance

Point the configured hostname at your ingress, verify the certificate and the
controller's permitted path, then log in with the privately provisioned account.
No Internet is the login default. Select Internet only for non-sensitive dependency
preparation. Each environment has a different runtime and persistent claims.

Do not consider a Ready pod sufficient. Run [acceptance](ACCEPTANCE.md), including
real login, workspace creation, tools, persistence, peer denials and network
tests. Empty first-use workspaces use an explicit `/workspace` Documents override;
no desktop `xdg-user-dir` package is required.

## Change and rollback

Save coherent image/profile/manifests and storage checkpoints under ignored
`private/` before changes. Stop the single writer for coherent filesystem copies.
Restore the matching profile before starting an older image; never overwrite
newer state with an old checkpoint automatically. Keep separate backups for
database, user state/workspaces, auth state and required Secrets. Test restore.

This reference is not a migration tool for an existing installation. It does not
discover previous users, infer ownership or import historical credentials.
