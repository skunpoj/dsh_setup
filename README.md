# DeepSeek Harness (DSH) Sovereign Cluster Setup & Enterprise Auth Gateway

Enterprise-Ready DeepSeek Harness (DSH) deployment on **Kubernetes GPU Cluster** with **Multi-User Web Login Gate, LiteLLM Gateway Integration & Reverse Proxy Architecture**

---

## 🏛️ Architecture Overview

```
                      HTTPS / WSS Request
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│       Kubernetes Ingress-Nginx (dsh.example.com)     │
│             SSL Wildcard: dsh-tls-secret             │
└─────────────────────────────┬───────────────────────────────┘
                              │ Port 3080
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 Pod: dsh (Namespace: llm)                   │
│                                                             │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ 🔐 Web Login Auth Proxy & Session Gate (Node.js :3080)│   │
│   │  • Branded Login Form (/login)                      │   │
│   │  • Session Cookie Management                        │   │
│   │  • Dynamic User Isolation: /workspace/users/<user>  │   │
│   │  • DSH One-Time Token Auto-Capture & Handshake      │   │
│   │  • Full HTTP & WebSocket Upgrades Forwarding        │   │
│   └──────────────────────────┬──────────────────────────┘   │
│                              │ Forward to 127.0.0.1:3081    │
│                              ▼                              │
│   ┌─────────────────────────────────────────────────────┐   │
│   │ 🤖 DeepSeek Harness Engine (DSH Web CLI on :3081)   │   │
│   │  • In-House LLM Gateway: DEEPSEEK_BASE_URL (LiteLLM)│   │
│   │  • Multi-Model Catalog: GLM-5.3, Qwen-Flash-Next,   │   │
│   │    Qwen3.8-27B (MIG 94GB), DeepSeek-V4-Flash        │   │
│   │  • Pre-initialized Settings: /root/.dsh/settings.yaml│  │
│   │  • Shared Enterprise Storage: /workspace (158.7 TB) │   │
│   │  • Azure DevOps Git Integration via PAT             │   │
│   └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 📁 Repository Structure & Dual-Remote Sync

The setup is actively synchronized across two repositories:
1. **Azure DevOps (Internal Sovereign)**: `https://github.com/skunpoj/dsh_setup.git`
2. **GitHub Enterprise / Personal**: `https://github.com/skunpoj/dsh_setup`

```
.
├── k8s/
│   ├── deployment.yaml       # Kubernetes Deployment (Node:22-alpine + DSH + Proxy)
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
  - Direct UI tabs on the login gate for:
    - **เข้าสู่ระบบ (Sign In)**
    - **สร้างบัญชีผู้ใช้ใหม่ (Create Account)**: Automatically sets up user workspace `/workspace/users/<username>` and persists credentials in `/workspace/users/.user_auth.json`.
    - **เปลี่ยนรหัสผ่าน (Change Password)**: Secure in-place password update verifying previous credentials.
- **Security Guard**: Full HTTP REST API and WebSocket connection protection. Requests without valid session cookies are redirected to login.
- **Default System Accounts**:
  - `admin`: Full administrative access
  - `kim`: Analytical workspace
  - `somchai`: Engineering workspace

### 2. Zero-Cost In-Cluster LLM Gateway (`DEEPSEEK_BASE_URL`)
- **Internal LiteLLM Service**: `http://litellm.llm.svc.cluster.local:4000/v1`
- **Configured Models**:
  - `glm-5.3-flash`: Default agile model for coding & conversation (128k context)
  - `qwen3.8-flash-next`: Next-gen agile reasoning model
  - `qwen3.8-27b`: Continuous batching on NVIDIA MIG 94GB GPU slice
  - `deepseek-v4-flash`: Cluster-hosted DeepSeek V4 model
- **vLLM Context Limit & Token Clamping Guard**:
  - Transparently clamps wire `max_tokens` to `4096` to prevent `litellm.BadRequestError: max_tokens=256000 cannot be greater than max_model_len=4096`.
  - LiteLLM parameter handling drops unsupported parameters (`thinking`, `reasoning_effort`) gracefully.

### 3. Settings Provider Persistence & Browser Access Guard
- Solves the DSH web UI error: `"Loading the provider directory failed: settings are unavailable in this browser"`.
- Container entrypoint explicitly creates `/root/.dsh/settings.yaml` (`echo "version: 1" > /root/.dsh/settings.yaml`), allowing `@deepseek-ai/dsh-settings-file` to register and serve `settings/describe` RPC calls seamlessly.
- Automatically enables `host` persistence in `@deepseek-ai/dsh-client-ui-settings` for authorized enterprise domain sessions (`dsh.example.com`).

### 4. Dynamic Multi-Tenant Workspaces
- **Backing PVC**: `da-workspace-pvc` (158.7 TB shared CephFS/NAS).
- **Personal Directories**: Automatically created on login at `/workspace/users/<username>`.
- **Root Aliases**:
  - `/root/workspace` -> `/workspace`
  - `/root/users` -> `/workspace/users`

### 5. Automated Azure DevOps Git Integration
- Pre-configured Git credentials with SSL verification disabled for internal PKI.
- Developers can clone internal repos via HTTPS directly from inside the DSH workspace terminal:
  ```bash
  git clone https://github.com/skunpoj/<repo-name>.git
  ```

---

## 🛠️ Deployment & Maintenance Instructions

### 1. Deploy or Update
```bash
# Apply updated manifests
kubectl apply -f k8s/configmap.yaml -n llm
kubectl apply -f k8s/deployment.yaml -n llm
kubectl apply -f k8s/service.yaml -n llm
kubectl apply -f k8s/ingress.yaml -n llm

# Restart deployment to pull fresh scripts
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

Released under the MIT License.
