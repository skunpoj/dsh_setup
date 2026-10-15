# DeepSeek Harness (DSH) Cluster Deployment & Enterprise Auth Gateway

[![Base Image](https://img.shields.io/badge/Base%20OS-Ubuntu%2024.04%20LTS-E95420?logo=ubuntu&logoColor=white)](https://ubuntu.com/)
[![Runtime](https://img.shields.io/badge/Runtime-Node.js%2022%20LTS-339933?logo=node.js&logoColor=white)](https://nodejs.org/)
[![Python](https://img.shields.io/badge/Python-3.12%20%2B%20Pip-3776AB?logo=python&logoColor=white)](https://python.org/)
[![Terminal](https://img.shields.io/badge/Terminal-ttyd%201.7.7-blue)](https://github.com/tsl0922/ttyd)
[![Default Model](https://img.shields.io/badge/Default%20Model-DeepSeek--V4.1--Flash%20(128K)-10B981)](https://github.com/deepseek-ai)

Production-grade deployment of **DeepSeek Harness (DSH)** on Kubernetes with authenticated, session-sticky routing to two execution environments.

## Features, design decision, rationale, and setup

### Available environments and features

| Environment | Network access | Writable workspace and state | Intended use |
| --- | --- | --- | --- |
| **Secure / Internal (default)** | Restricted egress: cluster DNS and approved in-cluster services such as LiteLLM only | Dedicated Secure workspace, session storage, runtime state, and launch token | Work involving protected internal data |
| **Internet** | General Internet egress enabled | Separate staging workspace, session storage, runtime state, and launch token | Downloading dependencies and work that explicitly requires Internet access |

The login page selects the working environment. The authenticated session is pinned to that environment for HTTP, WebSocket, terminal, and proxied application traffic. Both environments use the same authentication gateway and shared LiteLLM/GPU inference service, while their writable data and runtime volumes remain separate. **Secure / Internal is a restricted-egress environment, not a strict air gap**, because it still communicates with approved internal cluster services.

Dependencies cross the boundary through a controlled package workflow rather than a shared writable workspace:

1. Internet downloads Python or npm artifacts into `/packages/incoming`.
2. An operator supplies a manifest containing the expected SHA-256 hashes and runs the suspended promotion Job.
3. The Job rejects unsafe paths, missing files, and hash mismatches before copying approved artifacts to `/packages/approved`.
4. Secure mounts `/packages/approved` read-only and installs in offline mode. Internet cannot mount the approved cache or the Secure workspace.

Other included features are the interactive web terminal, authenticated dynamic application proxy, persistent sessions and attachments, enterprise CA support, readiness-gated startup, and a DeepSeek-V4.1-Flash path aligned to a 131,072-token total context window with an 8,192-token output ceiling.

### Design decision and reason

The deployment uses **one gateway plus separate Secure and Internet CPU/RAM execution pools**, while keeping the expensive LiteLLM and four-GPU model service shared. This design was selected because:

- a UI-only Internet switch cannot enforce network policy inside one shared pod;
- mounting one writable workspace in both environments would let an Internet-capable process read protected data and could corrupt sessions through concurrent writers;
- separate workspaces and state preserve the network and data boundary without duplicating the GPU model;
- the approved package cache supports Internet-assisted dependency installation without giving Secure direct access to public repositories; and
- session pinning makes the selected environment consistent for browser, terminal, tools, and application-proxy traffic.

### Security architecture and trust boundaries

The security boundary is the **execution environment**, not an individual browser control and not an individual DSH user. Public HTTPS traffic terminates at the cluster ingress and reaches only `dsh-environment-gateway`. The gateway authenticates the user, creates an `HttpOnly; SameSite=Lax` session cookie, records the selected environment, and routes all HTTP, WebSocket, terminal, and dynamic application traffic to the same backend for the lifetime of that login session. Secure is selected when the client omits or supplies an invalid environment value, so the routing decision fails to the restricted environment.

| Boundary | Enforcement | Security effect |
| --- | --- | --- |
| Public client to gateway | Kubernetes Ingress, gateway authentication, session cookie, trusted-host handling | Unauthenticated requests do not reach either DSH execution pool |
| Gateway to execution pool | Session-sticky backend selection plus `dsh-environment-pool-ingress` NetworkPolicy | Only the gateway can initiate connections to pool ports `1024-65535` |
| Secure outbound traffic | Pod label `egress-mode: offline` plus `dsh-offline-egress` NetworkPolicy | Allows DNS and LiteLLM TCP `4000`; denies general Internet egress when the cluster CNI enforces NetworkPolicy |
| Internet outbound traffic | Pod label `egress-mode: online` plus `dsh-online-egress` NetworkPolicy | Permits outbound traffic for explicitly selected Internet sessions |
| Model access | LiteLLM API key from Kubernetes Secret and internal service URL | Both pools share inference without receiving a separate GPU deployment |
| Dependency transfer | Separate incoming and approved PVCs, operator manifest, SHA-256 verification, suspended promotion Job | Internet can submit artifacts but cannot approve them or write the Secure-mounted cache |

Secure/Internal is therefore **restricted-egress**, not air-gapped. It remains connected to cluster DNS, LiteLLM, the gateway through allowed inbound traffic, Kubernetes-provided storage, and other infrastructure needed to run the service. A true air gap would require a physically or administratively disconnected platform and an offline media-transfer process.

### Data isolation and environment interaction

The pools never mount the same writable workspace or DSH runtime state:

| Data class | Secure / Internal | Internet | Shared? |
| --- | --- | --- | --- |
| Project workspace | `dsh-secure-workspace` at `/workspace` | `dsh-internet-staging` at `/workspace` | No |
| Sessions, storages, and attachments | `dsh-secure-state` at `/state` | `dsh-internet-state` at `/state` | No |
| DSH launch token | `dsh-secure-token` | `dsh-internet-token` | No; gateway mounts each token volume read-only |
| Login identities and environment preference | Gateway-owned `dsh-auth-state` | Gateway-owned `dsh-auth-state` | Yes, at the gateway only |
| Downloaded package candidates | Not mounted | `dsh-package-incoming` read/write | No |
| Approved dependency cache | `dsh-package-approved` read-only | Not mounted | No direct sharing; the promotion Job is the only bridge |
| LiteLLM/GPU inference | Internal LiteLLM service | Internal LiteLLM service | Yes |

Selecting Internet does not expose the Secure workspace, history, attachments, credentials, or launch token to the Internet pod. Selecting Secure does not expose the Internet staging workspace. Moving a project or data set between environments is a separate, operator-approved copy operation; it is not performed automatically when a user logs out or selects another environment. Session history also remains with the environment in which it was created.

Package transfer is deliberately one-way and mediated. The Internet pool writes candidates only to `incoming`. The promotion Job reads `incoming` and an operator-maintained approval manifest, rejects absolute paths, parent-path traversal, missing files, extra manifest fields, empty approvals, and SHA-256 mismatches, then writes approved files with mode `0444`. Secure mounts only that approved result and forces Python and npm to resolve in offline mode. Application data must never use this package path as a general file-transfer channel.

### Permission model

- **End user:** may authenticate, choose Secure or Internet for a new login session, and use DSH, terminal, tools, and proxied applications inside the selected environment. The user cannot change the environment of an existing authenticated session.
- **Gateway:** may read and update the central login store and environment preference, read each pool's launch token, and proxy authenticated traffic. It does not mount either workspace or either DSH state volume.
- **Secure and Internet runtimes:** may write only their own workspace, state, and token volumes. Secure can read the approved cache; Internet can write the incoming cache. Neither runtime mounts the other environment's data volumes.
- **Package approver/operator:** reviews artifact origin and hashes, updates `dsh-package-approval`, and explicitly resumes the suspended promotion Job. Downloading a package does not grant approval.
- **Kubernetes/platform administrator:** provisions Secrets and storage, pins the immutable image digest, applies NetworkPolicies, controls ingress, performs approved migrations, and retains rollback authority.
- **Model service:** is shared infrastructure reached through LiteLLM. The runtime receives its LiteLLM credential from `dsh-runtime-secrets`; secret values are not stored in this repository.

The current gateway uses a persistent local JSON credential store and in-memory login sessions. This is an application authentication mechanism, not corporate SSO, Kubernetes RBAC, or a hardware-backed identity boundary. Protect and back up the authentication PVC, restrict administrative access, rotate exposed credentials, and use an approved identity provider or a password-hashing migration before treating it as an enterprise identity authority.

### Execution containment

Both DSH pools and the package promotion Job run as Linux UID/GID `10001`, require `runAsNonRoot`, disable privilege escalation, and drop all Linux capabilities. Each DSH container is limited to 4 CPU and 8 GiB memory, with readiness and liveness probes preventing an unready process from receiving gateway traffic. Images are pinned by digest so a deployment cannot silently move to different bytes under the same tag.

NetworkPolicy and volume mounts provide environment-level containment, but the DSH runtime remains an interactive development environment. Users can execute shell commands and code inside the selected pool. The current manifests do not set a read-only root filesystem, a dedicated seccomp profile, or one pod/PVC per human identity. Multiple authenticated users routed to the same environment share that environment's DSH process and mounted files, so this design **does not provide hostile-user isolation inside one pool**. Use dedicated per-user pods/PVCs, stronger runtime sandboxing, quotas, and corporate identity integration if users must be mutually untrusted.

Network enforcement also depends on a Kubernetes CNI that implements NetworkPolicy. Validate the effective policies after every cluster or CNI change with an actual denied Secure egress request, an allowed LiteLLM request, an allowed Internet request, and a check that neither pod contains the other environment's mounts. A successful manifest apply alone is not proof of containment.

### Current Production deployment

- Public DSH ingress routes through `dsh-environment-gateway`.
- Secure and Internet pools run immutable image digest `sha256:d3a300605a87aa63ec4a2588f827658a132407ff17908ba49403fa7cca8d261a`, built by Azure build `62647` from GPU infrastructure commit `f55f439659aa6946b60b1189df90bc76062821d6`.
- Secure egress permits cluster DNS and the in-cluster LiteLLM service only; Internet egress is enabled.
- Authentication is shared at the gateway; pool state, session storage, workspace, launch token, and package directories are separate.
- DeepSeek-V4.1-Flash, LiteLLM, and the DSH catalog use the verified 131,072-token guardrail.

### Setup method

Prerequisites are Kubernetes access to namespace `llm`, the immutable DSH runtime image in the approved registry, the existing LiteLLM service, a compatible default StorageClass, and `dsh-runtime-secrets` provisioned through the approved secret-management process with key `litellm-api-key`. Do not place secret values in Git or shell history.

1. Build and verify the immutable runtime image with `azure-pipelines.yml`. Pin its digest in `k8s/dsh-environment-pools.yaml` and `k8s/dsh-environment-gateway.yaml`.
2. Review host names, service names, storage sizes, and the NetworkPolicy namespace selectors for the target cluster.
3. Apply the execution pools, gateway, egress policies, and suspended package-promotion Job:

   ```bash
   kubectl apply -f k8s/dsh-environment-pools.yaml
   kubectl apply -f k8s/dsh-environment-gateway.yaml
   kubectl apply -f k8s/dsh-egress-policies.yaml
   kubectl apply -f k8s/dsh-package-promotion.yaml
   ```

4. Route the public DSH ingress to service `dsh-environment-gateway` on port `3080`. Use `k8s/dsh-auth-migration.yaml` only during a controlled migration of approved legacy authentication/workspace data.
5. Wait for `dsh-secure`, `dsh-internet`, and `dsh-environment-gateway` to become Available. Verify login and logout, Secure-default selection, Internet selection, session pinning, terminal and application proxying, restart persistence, Secure egress denial, Internet egress, shared inference, and checksum-gated package promotion before scaling down the rollback deployment.

Detailed policy, package-transfer, migration, rollback, and upstream-sync procedures are in [UPSTREAM_SYNC_AND_INTERNET_POLICY.md](docs/UPSTREAM_SYNC_AND_INTERNET_POLICY.md) and [OPERATIONS_AND_TROUBLESHOOTING_MANUAL.md](docs/OPERATIONS_AND_TROUBLESHOOTING_MANUAL.md).

---

## 🏛️ Legacy single-pod architecture

The diagram below describes the earlier deployment retained only as rollback context. The current Production path is `Ingress -> authenticated environment gateway -> Secure or Internet pool -> shared LiteLLM -> shared GPU model`.

```
                               HTTPS / WSS Inbound Traffic
                                            │
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                      Kubernetes Ingress-Nginx (*.example.com)                          │
│                             TLS Secret: dsh-tls-secret                                 │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │ Port 3080
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                Pod: dsh (Namespace: llm)                               │
│                                                                                        │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │ 🔐 Enterprise Auth Proxy & Session Gate (Node.js Port 3080)                     │   │
│   │  • Web-based Login, Registration, and Password Reset Portal (/login)          │   │
│   │  • Dynamic Subdomain (*-<port>.domain) & Path (/proxy/<port>/) App Gateway     │   │
│   │  • HTTP REST, SSE & WebSocket Upgrades (Streamlit, Vite HMR, ttyd)             │   │
│   │  • DSH Launch Token Interception & Session Cookie Injection                    │   │
│   └───────────────┬───────────────────────┬───────────────────────┬────────────────┘   │
│                   │                       │                       │                    │
│      Forward to   │ Port 3081             │ Port 7681             │ Port N             │
│      127.0.0.1    ▼                       ▼                       ▼                    │
│   ┌───────────────────────────┐ ┌───────────────────┐ ┌───────────────────────────┐   │
│   │ 🤖 DeepSeek Harness Engine│ │ 🖥️ Interactive Web│ │ 🚀 User Applications      │   │
│   │  • Ubuntu 24.04 + Node 22 │ │    Terminal (ttyd)│ │  • Streamlit (8501)       │   │
│   │  • Python 3.12 + Pip + venv││  • Port 7681      │ │  • FastAPI / Uvicorn (8000│   │
│   │  • In-Cluster LLM Gateway │ │  • Full bash -l   │ │  • Flask / Gradio (5000)  │   │
│   │  • DeepSeek-V4.1-Flash 128K││  • WebSocket stream││  • Next.js / React (3000) │   │
│   └───────────────────────────┘ └───────────────────┘ └───────────────────────────┘   │
│                   │                       │                       │                    │
│                   └───────────────────────┼───────────────────────┘                    │
│                                           ▼                                            │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │ 💾 Persistent Storage Layer (Kubernetes PVC mounted at /workspace)              │   │
│   │  • Multi-Tenant User Homes: /workspace/users/<username>/                       │   │
│   │  • Git Repositories: /workspace/repos/                                         │   │
│   │  • State & Sessions: /workspace/dsh_storage/                                   │   │
│   │  • Background Sync Watcher: 10s auto-reconciliation loop                       │   │
│   └────────────────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🌟 Full Feature Matrix

### 1. Ubuntu 24.04 LTS Runtime & GLIBC Foundation
- **Modern Linux Stack**: Replaces Alpine (`musl` libc) with official **Ubuntu 24.04 LTS (Noble Numbat)** powered by `glibc 2.39`.
- **Pre-compiled Wheel Compatibility**: Eliminates loader errors (`ld-linux-x86-64.so.2 not found`) when running native binaries like `python-build-standalone`, uv, PyTorch, and compiled C-extensions.
- **Developer Toolchain**: Bundles `Python 3.12.3`, `pip 24.0`, `python3-venv`, `build-essential` (`gcc 13.3.0`, `g++ 13.3.0`, `make 4.3`), `git`, `curl`, `socat`, and `jq`.
- **Node.js 22 LTS**: Powered by official NodeSource Node.js 22 distribution.

### 2. Interactive Web Terminal (`ttyd`)
- **Direct Web Terminal**: Integrated `ttyd` (xterm.js web terminal) on port 7681, reachable only through the authenticated gateway under the pool ingress NetworkPolicy.
- **Full Shell Capabilities**: Spawns an interactive login bash shell (`bash -l`) with ANSI color, tab completion, nano/vim, and git.
- **Zero-Trust Access**: Terminal port is strictly protected behind the enterprise authentication proxy.
- **Access Routes**: Accessible via `https://<tenant>-terminal.example.com` or `https://<tenant>.example.com/proxy/terminal/`.

### 3. Dual Dynamic Application Reverse Proxy Gateway
- **Option 1 (Wildcard Subdomains)**: `https://<tenant>-<port>.example.com` (e.g., `dsh-8501.example.com`).
  - Perfect for single-page applications (Vite, Next.js, Streamlit, Gradio) that load assets from root `/`.
- **Option 2 (Dynamic Path Proxy)**: `https://<tenant>.example.com/proxy/<port>/` (e.g., `dsh.example.com/proxy/8501/`).
  - Forwards any arbitrary port (`1`–`65535`) dynamically on the fly without DNS changes.
- **Full WebSocket / SSE Support**: Transparent HTTP `Upgrade` forwarding for Streamlit state, Vite HMR, and WebSocket servers.
- **Named Port Aliases**: Define friendly aliases in `/workspace/.ports.json` (e.g., `{"dashboard": 8501, "api": 8000}`).

### 4. Enterprise Web Authentication & Session Gate
- **No CLI Token Hassle**: Users authenticate via the Web Login Portal at `/login`.
- **Self-Service Onboarding**:
  - **Sign In**: Authenticates through the gateway's persistent local credential store. See the security-boundary limitations above; the current store is not corporate SSO and should be migrated to approved password hashing or an enterprise identity provider.
  - **Create Account**: Adds an identity to the gateway's persistent credential store. It does not provision a dedicated pod or isolated per-user workspace; authenticated users share the selected environment's execution boundary.
  - **Change Password**: Secure in-place password modification.
- **Token Capture & Reverse Proxy Invariant**: Automatically intercepts the one-time DSH launch token on container boot, mints authority-bound session cookies, and injects credentials into downstream REST calls (e.g., `/api/directoryPicker/list`), eliminating HTTP 401/403 remote proxy issues.

### 5. In-Cluster LLM Gateway & DeepSeek-V4.1-Flash Default
- **In-Cluster Inference**: Connects directly to internal OpenAI-compatible endpoints (LiteLLM / vLLM) with zero public API cost.
- **Default Model**: **DeepSeek-V4.1-Flash** (verified 128K gateway context window, 8,192 max output tokens).
- **Standby Catalog**: Pre-registers `deepseek-flash`, `glm-5.3-flash`, and `qwen3.8-27b`.
- **Token Clamping**: Automatically clamps requested `max_tokens` to model limits to prevent gateway overflow rejections.
- **Effective Context**: The DSH profile, LiteLLM metadata and clamper, and active SGLang server are aligned to a 131,072-token total context window. Automatic compaction starts around 98,304 tokens, with an 8,192-token output cap and a 256-token LiteLLM safety buffer.
- **Readiness-Gated Rollout**: Kubernetes publishes a DSH pod only after its internal engine listens on port 3081, preventing traffic from reaching the several-minute bootstrap phase.

### 6. Environment-isolated workspaces and persistent state
- **Secure workspace**: Protected project data and migrated legacy history remain in the Secure pool PVC.
- **Internet staging**: Internet sessions use a separate writable staging PVC and cannot mount the protected workspace.
- **Controlled dependency transfer**: Internet downloads enter an incoming package area. Secure mounts only the separately promoted approved package cache as read-only.
- **Security boundary**: The pools isolate the two network environments. This design does not claim cryptographic isolation between human accounts authenticated through the same gateway.

### 7. Enterprise Root CA & SSL Inspection Support
- **Custom PKI Trust**: Automatically detects and registers custom enterprise CA certificates mounted into `/usr/local/share/ca-certificates/`.
- **Runtime Propagation**: System store updates propagate to OpenSSL, Curl, Python (`REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`), Node.js (`NODE_EXTRA_CA_CERTS`), and Git (`http.sslCAInfo`).
- **Complete Setup Guide**: See [docs/ENTERPRISE_ROOT_CA_SETUP.md](docs/ENTERPRISE_ROOT_CA_SETUP.md).

### 8. Zero-Data-Loss Session & State Persistence (PreStop Lifecycle Hook)
- **Decoupled Fast Storage**: Session histories, SQLite databases, and lockfiles are maintained on local container rootfs (`/root/.dsh/`) to guarantee microsecond POSIX locking and bypass SMB/CIFS latency.
- **Synchronous PreStop Hook**: A Kubernetes `lifecycle.preStop` hook triggers immediately before pod termination, executing a synchronous flush of all active sessions, storages, attachments, and credentials to CIFS with `terminationGracePeriodSeconds: 60`.
- **Lock Purge on Boot**: Automatically eliminates stale SMB/CIFS `session.lock` files on pod recreation, ensuring zero locked sessions after unexpected restarts.

### 9. Attachment Resilience & Crash Immunity
- **Missing Object Recovery**: When historical image or file attachments are missing from disk (`ENOENT`), upstream DSH typically throws fatal `AttachmentError("Attachment object is missing.")`, permanently locking the conversation turn.
- **Self-Healing Fallback**: Section 11 of `configure_models.js` intercepts `readImageFile` in `@deepseek-ai/dsh-attachment-local`, generating and returning a synthetic 1x1 transparent PNG placeholder. Chat turns, session controllers, and thumbnail renderers complete smoothly without interruption.

### 10. Supervised Data Quality (DQ) & Multi-Port Server Architecture
- **Persistent Report Daemons**: Container startup automatically spawns supervised HTTP servers on ports `8099` and `8899` serving project deliverables and Data Quality reports.
- **Instant Gateway Access**: Accessible seamlessly via the dynamic reverse proxy at `https://dsh.aiportal.bot.or.th/proxy/8099/dq_report.html` and `/proxy/8899/dq_report.html`.

---

## 📁 Repository Directory Structure

```
.
├── Dockerfile                              # Multi-stage Ubuntu 24.04 image with Python 3.12, Node 22 & ttyd
├── README.md                               # Master system documentation & deployment manual
├── cordis_plugin/
│   └── index.ts                            # Cordis Plugin (cordis-plugin-custom-llm-gateway)
├── docs/                                   # Dedicated feature guides & manuals
│   ├── OPERATIONS_AND_TROUBLESHOOTING_MANUAL.md # Authoritative Enterprise Operations & Troubleshooting Manual
│   ├── DYNAMIC_APP_GATEWAY.md              # Deep dive on Subdomain & Path proxy routing + ttyd
│   ├── ENTERPRISE_ROOT_CA_SETUP.md         # Step-by-step Enterprise CA extraction & mounting
│   └── MULTI_TENANT_STORAGE_AND_PERSISTENCE.md # Storage tiers, preStop hook & zero-data-loss
├── k8s/
│   ├── configmap.yaml                      # ConfigMap containing auth_proxy.js & configure_models.js
│   ├── deployment.yaml                     # Kubernetes Deployment manifest (Ubuntu 24.04 + preStop hook)
│   ├── ingress.yaml                        # Ingress manifest with wildcard host routing
│   └── service.yaml                        # ClusterIP Service manifest (Port 3080)
├── scripts/
│   ├── auth_proxy.js                       # Enterprise Auth Proxy, login UI, session gate & proxy
│   └── configure_models.js                 # Script injecting In-Cluster models & resilience patches
└── upstream_rfc/
    └── RFC_ENTERPRISE_CORDIS_PLUGIN_AND_GATEWAY.md # Upstream specification RFC
```

---

## 🛠️ Step-by-Step Deployment Guide

### Prerequisites
- Kubernetes cluster (v1.24+)
- Ingress Controller with Wildcard TLS support (e.g. Ingress-Nginx)
- Existing PersistentVolumeClaim (e.g. `dsh-workspace-pvc`)

### Step 1: Create Admin Secret
Create the initial administrator secret for the auth proxy:
```bash
kubectl create secret generic dsh-auth -n llm \
  --from-literal=admin-password='YourStrongAdminPasswordHere'
```

### Step 2: Configure Ingress Domain
Edit `k8s/deployment.yaml` and set `DSH_TRUSTED_HOST` to your domain:
```yaml
        env:
          - name: DSH_TRUSTED_HOST
            value: "dsh.example.com"
          - name: DSH_COOKIE_DOMAIN
            value: ".example.com"  # Optional: defaults to parent domain
```

### Step 3: Deploy Manifests
```bash
# Apply ConfigMap, Deployment, Service, and Ingress
kubectl apply -f k8s/configmap.yaml -n llm
kubectl apply -f k8s/deployment.yaml -n llm
kubectl apply -f k8s/service.yaml -n llm
kubectl apply -f k8s/ingress.yaml -n llm
```

### Step 4: Verify Rollout
```bash
# Verify pod status
kubectl get pods -n llm -l app=dsh

# Tail container boot logs
kubectl logs -n llm deployment/dsh -c dsh --tail=100 -f
```

---

## ⚙️ Environment Variables Reference

| Variable | Default Value | Description |
| :--- | :--- | :--- |
| `DSH_TRUSTED_HOST` | `dsh.example.com` | Public Ingress hostname passed to DSH engine |
| `DSH_COOKIE_DOMAIN` | Parent of `DSH_TRUSTED_HOST` (e.g. `.example.com`) | Cookie domain shared with the app subdomains; never derived from the request's Host header |
| `DSH_COOKIE_NAME` | `dsh_auth` | Name of the session cookie; give each DSH instance on the same cookie domain its own name (e.g. `dsh2_auth`) so their logins do not overwrite each other |
| `DSH_AUTH_PASS` | *(from Secret `dsh-auth`)* | Administrator password; the proxy refuses to start without it unless a user store already exists |
| `PORT` | `3080` | Port where `auth_proxy.js` listens |
| `DSH_PORT` | `3081` | Internal port where DSH engine listens |
| *(fixed)* | `7681` | Internal port where the `ttyd` web terminal listens (alias `terminal`) |
| `WORKSPACE_ROOT` | `/workspace/users` | Base path for partitioned user workspaces |
| `REQUESTS_CA_BUNDLE`| `/etc/ssl/certs/ca-certificates.crt` | CA trust bundle for Python `requests` |
| `SSL_CERT_FILE` | `/etc/ssl/certs/ca-certificates.crt` | CA trust bundle for OpenSSL / urllib |
| `NODE_EXTRA_CA_CERTS`| `/etc/ssl/certs/ca-certificates.crt` | CA trust bundle for Node.js runtimes |

---

## 🔍 Verification & Health Checks

Exec into the running DSH container to verify all subsystems:

```bash
POD=$(kubectl get pod -n llm -l app=dsh -o jsonpath='{.items[0].metadata.name}')

# 1. Verify OS and C runtime
kubectl exec -n llm $POD -- cat /etc/os-release | grep PRETTY_NAME

# 2. Verify tool versions
kubectl exec -n llm $POD -- python3 --version
kubectl exec -n llm $POD -- pip3 --version
kubectl exec -n llm $POD -- gcc --version | head -n 1
kubectl exec -n llm $POD -- node -v
kubectl exec -n llm $POD -- npm -v
kubectl exec -n llm $POD -- dsh --version

# 3. Test local internal service ports
kubectl exec -n llm $POD -- curl -s -I http://127.0.0.1:3080/ | head -n 3 # Auth Proxy
kubectl exec -n llm $POD -- curl -s -I http://127.0.0.1:3081/ | head -n 3 # DSH Web
kubectl exec -n llm $POD -- curl -s -I http://127.0.0.1:7681/ | head -n 3 # ttyd Terminal
kubectl exec -n llm $POD -- curl -s -I http://127.0.0.1:8099/dq_report.html | head -n 3 # Supervised DQ Server 8099
kubectl exec -n llm $POD -- curl -s -I http://127.0.0.1:8899/dq_report.html | head -n 3 # Supervised DQ Server 8899

# 4. Verify Resilience & Self-Healing Patches
kubectl logs -n llm $POD -c dsh | grep -E "dsh-attachment-local|dsh-llm-pi-ai|SHUTDOWN-TRAP"
```

---

## 📚 Specialized Documentation Guides & Manuals

- 📖 **[Authoritative Operations & Troubleshooting Manual](docs/OPERATIONS_AND_TROUBLESHOOTING_MANUAL.md)** *(Comprehensive user guide, administration runbook, self-healing architecture & 8 disaster recovery scenarios)*
- 💾 **[Multi-Tenant Storage & Zero-Data-Loss Persistence Guide](docs/MULTI_TENANT_STORAGE_AND_PERSISTENCE.md)** *(Decoupled storage tiers, CIFS lock prevention & PreStop lifecycle synchronization)*
- 🌐 **[Dynamic Application Gateway & Web Terminal Guide](docs/DYNAMIC_APP_GATEWAY.md)** *(Subdomain & Path proxy routing, WebSocket streaming & ttyd terminal)*
- 🔐 **[Enterprise Root CA & SSL Inspection Setup Guide](docs/ENTERPRISE_ROOT_CA_SETUP.md)** *(Step-by-step Enterprise CA extraction & runtime mounting)*
- 📜 **[Enterprise Cordis Plugin & Gateway RFC](upstream_rfc/RFC_ENTERPRISE_CORDIS_PLUGIN_AND_GATEWAY.md)** *(Upstream specification RFC for custom LLM gateway injection)*

---

## 📄 License

Released under the [MIT License](LICENSE).
