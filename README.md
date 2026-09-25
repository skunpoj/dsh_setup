# DeepSeek Harness (DSH) Cluster Deployment & Enterprise Auth Gateway

Enterprise-grade deployment of **DeepSeek Harness (DSH)** on Kubernetes with:
- **Default Local Model**: **DeepSeek-V4.1-Flash** (Native 1M Context Window CED MoE)
- **Multi-Tenant User Isolation**: Per-user directory sandboxes and storage isolation
- **Reverse Proxy Authentication Gate**: Session-to-cookie translation solving `directoryPicker` remote access
- **Cordis Plugin**: `cordis-plugin-custom-llm-gateway` for dynamic provider and model catalog registration

---

## 🏛️ Architecture Overview

```
                      HTTPS / WSS Request
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│       Kubernetes Ingress-Nginx (dsh.example.com)            │
│             TLS Secret: dsh-tls-secret                      │
└─────────────────────────────┬───────────────────────────────┘
                              │ Port 3080
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 Pod: dsh (Namespace: llm)                   │
│                                                             │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ 🔐 Web Login Auth Proxy & Session Gate (Node.js :3080)│   │
│   │  • Web-based Login Form (/login)                    │   │
│   │  • Session Cookie Management                        │   │
│   │  • Dynamic User Isolation: /workspace/users/<user>  │   │
│   │  • DSH Launch Token Auto-Capture & Cookie Minting   │   │
│   │  • Full HTTP REST & WebSocket Upgrades Forwarding   │   │
│   └──────────────────────────┬──────────────────────────┘   │
│                              │ Forward to 127.0.0.1:3081    │
│                              ▼                              │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ 🤖 DeepSeek Harness Engine (DSH Web on :3081)       │   │
│   │  • Default Model: DeepSeek-V4.1-Flash (Native 1M)   │   │
│   │  • Provider Gateway: In-Cluster LiteLLM / vLLM      │   │
│   │  • Pre-initialized Settings: /root/.dsh/settings.yaml│  │
│   │  • Isolated User Storage: /workspace (PVC)          │   │
│   │  • Cordis Custom LLM Gateway Plugin                 │   │
│   └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 📁 Repository Structure

```
.
├── cordis_plugin/
│   └── index.ts              # Cordis Plugin (cordis-plugin-custom-llm-gateway)
├── k8s/
│   ├── deployment.yaml       # Kubernetes Deployment (Ubuntu 24.04 + Node 22 + Python 3.12 + DSH + Proxy)
│   ├── service.yaml          # ClusterIP Service (Port 3080)
│   ├── ingress.yaml          # Ingress Resource (dsh.example.com)
│   └── configmap.yaml        # ConfigMap holding proxy & model patch scripts
├── scripts/
│   ├── auth_proxy.js         # Enterprise Login Gate & Reverse Proxy
│   └── configure_models.js   # Script injecting In-Cluster models to DSH catalog
└── README.md                 # System documentation & deployment guide
```

---

## 🚀 Key Operational Features

### 1. Enterprise Web Authentication & User Self-Service Gate
- **No CLI Token Hassle**: Users log in via the Web Login Portal at `https://dsh.example.com/login`.
- **Self-Service User Registration & Password Change**:
  - Direct UI tabs on the login gate:
    - **Sign In**
    - **Create Account**: Automatically sets up user workspace `/workspace/users/<username>` and persists credentials in `/workspace/users/.user_auth.json`.
    - **Change Password**: Secure in-place password update verifying previous credentials.
- **Remote Access & Cookie Exchange**: Intercepts the one-time launch token at container startup, mints upstream authority-bound session cookies, and injects them into downstream REST calls (e.g. `/api/directoryPicker/list`), preventing HTTP 401/403 errors when accessed via reverse proxies.

### 2. In-Cluster LLM Gateway & DeepSeek-V4.1-Flash Default
- **Internal Inference Gateway**: OpenAI-compatible endpoint (LiteLLM / vLLM).
- **Default Primary Model**:
  - `deepseek-v4.1-flash`: **DeepSeek-V4.1-Flash (Native 1M CED MoE)** with 1,048,576 context window and 65,536 max output tokens.
- **Standby Models**:
  - `deepseek-flash`: Alias for DeepSeek-V4.1-Flash
  - `glm-5.3-flash`: Standby low-latency model
  - `qwen3.8-27b`: Agile reasoning model
- **Context Limit & Token Clamping Guard**:
  - Clamps wire `max_tokens` to model limits, avoiding upstream context overflow rejections.

### 3. Settings Provider Persistence & Browser Access Guard
- Addresses DSH web UI issue: `"Loading the provider directory failed: settings are unavailable in this browser"`.
- Container entrypoint initializes `/root/.dsh/settings.yaml` (`version: 1`), enabling `@deepseek-ai/dsh-settings-file` to register and serve `settings/describe` RPC calls reliably.
- Preserves `host` persistence in `@deepseek-ai/dsh-client-ui-settings` for authorized domain sessions.

### 4. Dynamic Multi-Tenant Workspaces & Storage Isolation
- **Storage Backend**: Kubernetes PersistentVolumeClaim (e.g. `subPath` isolation for shared volumes, or dedicated local block storage).
- **User Workspaces**: Partitioned by username under `/workspace/users/<username>`.
- **Mount Isolation**: Pods can mount dedicated PVC subpaths to prevent cross-tenant directory access.

### 5. Dynamic Application Port & Subdomain Reverse Proxy Gateway
- **Option 1 (Subdomain-based)**: `https://<tenant>-<port>.domain.com` (e.g. `https://dsh-8000.domain.com`, `https://dsh-8501.domain.com`)
  - Flawless single-page app (SPA) and dashboard asset compatibility where scripts load from `/`.
- **Option 2 (Path-based)**: `https://<tenant>.domain.com/proxy/<port>/` (e.g. `https://dsh.domain.com/proxy/8000/`, `https://dsh.domain.com/proxy/8501/`)
  - 100% dynamic port selection on the fly (1–65535); any server started inside DSH is immediately accessible.
- **WebSocket Upgrade Forwarding**: Supports real-time protocols for Streamlit, Vite/Next.js HMR, and WebSocket services.
- **Named Port Aliases**: Optional mapping via `/workspace/.ports.json` (e.g. `{"dashboard": 8501, "api": 8000}`).
- **Domain setup**: set `DSH_TRUSTED_HOST` in `k8s/deployment.yaml` to the public host (e.g. `dsh.example.com`); the agent's app links are built from it. Option 1 also needs a wildcard DNS record `*.example.com` pointing at the ingress controller, and the `dsh-tls-secret` certificate must cover both `dsh.example.com` and `*.example.com`. A wildcard matches one label, so every `*.example.com` host reaches this one Deployment; a second DSH instance on the same domain needs its own Ingress with explicit `dsh2-<port>` hosts or its own subdomain (e.g. `*.dsh2.example.com`).

---

## 🛠️ Deployment & Maintenance Instructions

### 1. Deploy or Update
```bash
# Create the admin password Secret (required; the auth proxy refuses to start without it)
kubectl create secret generic dsh-auth -n llm --from-literal=admin-password='<strong-password>'

# The Deployment mounts an existing PersistentVolumeClaim named dsh-workspace-pvc at /workspace;
# create it (or edit claimName in k8s/deployment.yaml) before applying.

# Apply Kubernetes manifests
kubectl apply -f k8s/configmap.yaml -n llm
kubectl apply -f k8s/deployment.yaml -n llm
kubectl apply -f k8s/service.yaml -n llm
kubectl apply -f k8s/ingress.yaml -n llm

# Restart deployment to load updated scripts
kubectl rollout restart deployment dsh -n llm
```

### 2. Operational Health Check
```bash
# Check Pod status
kubectl get pods -n llm -l app=dsh

# View container startup logs & token capture
kubectl logs -n llm deployment/dsh -c dsh --tail=100 -f
```

---

## 📄 License

Released under the MIT License.
