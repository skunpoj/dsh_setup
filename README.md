# DeepSeek Harness (DSH) Cluster Deployment & Enterprise Auth Gateway

[![Base Image](https://img.shields.io/badge/Base%20OS-Ubuntu%2024.04%20LTS-E95420?logo=ubuntu&logoColor=white)](https://ubuntu.com/)
[![Runtime](https://img.shields.io/badge/Runtime-Node.js%2022%20LTS-339933?logo=node.js&logoColor=white)](https://nodejs.org/)
[![Python](https://img.shields.io/badge/Python-3.12%20%2B%20Pip-3776AB?logo=python&logoColor=white)](https://python.org/)
[![Terminal](https://img.shields.io/badge/Terminal-ttyd%201.7.7-blue)](https://github.com/tsl0922/ttyd)
[![Default Model](https://img.shields.io/badge/Default%20Model-DeepSeek--V4.1--Flash%20(1M)-10B981)](https://github.com/deepseek-ai)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

Production-grade, enterprise deployment of **DeepSeek Harness (DSH)** on Kubernetes. Built on **Ubuntu 24.04 LTS (GLIBC)** with integrated multi-tenant session isolation, reverse-proxy authentication gate, dynamic application gateway, interactive web terminal, and in-cluster LLM integration.

---

## 🏛️ System Architecture

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
│   │  • DeepSeek-V4.1-Flash 1M │ │  • WebSocket stream││  • Next.js / React (3000) │   │
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
- **Direct Web Terminal**: Integrated `ttyd` (xterm.js web terminal) bound to `127.0.0.1:7681`.
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
  - **Sign In**: Authenticates against salted SHA-256 credentials in `/workspace/users/.user_auth.json`.
  - **Create Account**: Instantly provisions an isolated home workspace at `/workspace/users/<username>/`.
  - **Change Password**: Secure in-place password modification.
- **Token Capture & Reverse Proxy Invariant**: Automatically intercepts the one-time DSH launch token on container boot, mints authority-bound session cookies, and injects credentials into downstream REST calls (e.g., `/api/directoryPicker/list`), eliminating HTTP 401/403 remote proxy issues.

### 5. In-Cluster LLM Gateway & DeepSeek-V4.1-Flash Default
- **In-Cluster Inference**: Connects directly to internal OpenAI-compatible endpoints (LiteLLM / vLLM) with zero public API cost.
- **Default Model**: **DeepSeek-V4.1-Flash** (Native 1M Context Window CED MoE, 65,536 max tokens).
- **Standby Catalog**: Pre-registers `deepseek-flash`, `glm-5.3-flash`, and `qwen3.8-27b`.
- **Token Clamping**: Automatically clamps requested `max_tokens` to model limits to prevent gateway overflow rejections.

### 6. Multi-Tenant Workspaces & Storage Persistence
- **Partitioned User Storage**: Each tenant works inside `/workspace/users/<username>/`.
- **Symlink Layer**: Automatically maps `/workspace/dsh_storage/workspaces/<username>` to `/root/<username>` for transparent IDE compatibility.
- **Background Sync Watcher**: A 10-second background daemon continuously synchronizes `/root/.dsh/.credentials.yaml` and new user workspaces to the persistent volume.

### 7. Enterprise Root CA & SSL Inspection Support
- **Custom PKI Trust**: Automatically detects and registers custom enterprise CA certificates mounted into `/usr/local/share/ca-certificates/`.
- **Runtime Propagation**: System store updates propagate to OpenSSL, Curl, Python (`REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`), Node.js (`NODE_EXTRA_CA_CERTS`), and Git (`http.sslCAInfo`).
- **Complete Setup Guide**: See [docs/ENTERPRISE_ROOT_CA_SETUP.md](docs/ENTERPRISE_ROOT_CA_SETUP.md).

---

## 📁 Repository Directory Structure

```
.
├── Dockerfile                              # Multi-stage Ubuntu 24.04 image with Python 3.12, Node 22 & ttyd
├── README.md                               # Master system documentation & deployment manual
├── cordis_plugin/
│   └── index.ts                            # Cordis Plugin (cordis-plugin-custom-llm-gateway)
├── docs/                                   # Dedicated feature guides
│   ├── DYNAMIC_APP_GATEWAY.md              # Deep dive on Subdomain & Path proxy routing + ttyd
│   ├── ENTERPRISE_ROOT_CA_SETUP.md         # Step-by-step Enterprise CA extraction & mounting
│   └── MULTI_TENANT_STORAGE_AND_PERSISTENCE.md # User homes, storage layouts & sync watchers
├── k8s/
│   ├── configmap.yaml                      # ConfigMap containing auth_proxy.js & configure_models.js
│   ├── deployment.yaml                     # Kubernetes Deployment manifest (Ubuntu 24.04)
│   ├── ingress.yaml                        # Ingress manifest with wildcard host routing
│   └── service.yaml                        # ClusterIP Service manifest (Port 3080)
├── scripts/
│   ├── auth_proxy.js                       # Enterprise Auth Proxy, login UI, session gate & proxy
│   └── configure_models.js                 # Script injecting In-Cluster models into DSH catalog
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
| `DSH_COOKIE_DOMAIN` | Derived from host | Cookie domain for multi-tenant SSO across subdomains |
| `DSH_COOKIE_NAME` | `dsh_auth` | Name of the authentication session cookie |
| `DSH_ADMIN_PASSWORD`| *(from Secret)* | Master administrator password |
| `PORT` | `3080` | Port where `auth_proxy.js` listens |
| `DSH_PORT` | `3081` | Internal port where DSH engine listens |
| `TERMINAL_PORT` | `7681` | Internal port where `ttyd` web terminal listens |
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
```

---

## 📚 Specialized Documentation Guides

- [Enterprise Root CA & SSL Inspection Setup Guide](docs/ENTERPRISE_ROOT_CA_SETUP.md)
- [Dynamic Application Gateway & Web Terminal Guide](docs/DYNAMIC_APP_GATEWAY.md)
- [Multi-Tenant Workspaces & Storage Persistence Guide](docs/MULTI_TENANT_STORAGE_AND_PERSISTENCE.md)
- [Enterprise Cordis Plugin & Gateway RFC](upstream_rfc/RFC_ENTERPRISE_CORDIS_PLUGIN_AND_GATEWAY.md)

---

## 📄 License

Released under the [MIT License](LICENSE).
