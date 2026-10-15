> **Legacy manual notice — 15 October 2026:** the CIFS/rootfs diagrams and startup procedures below describe the legacy deployment, not the current Secure/Internet pools. They do not prove zero data loss or per-user isolation. Use [the current walkthrough](DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.html) and [storage guide](MULTI_TENANT_STORAGE_AND_PERSISTENCE.md) as current authority.

# DeepSeek Harness (DSH) Operations & Troubleshooting Manual

> **Authoritative Enterprise Operations, Administration & User Manual**
> *Production Deployment on Kubernetes (Ubuntu 24.04 LTS + Node 22 + LiteLLM / vLLM)*

---

## 📑 Table of Contents

1. [Architecture & System Topology](#1-architecture--system-topology)
2. [End-User Operating Manual](#2-end-user-operating-manual)
   - [2.1 Access & Web Authentication](#21-access--web-authentication)
   - [2.2 Session Management & Workspaces](#22-session-management--workspaces)
   - [2.3 Model Catalog & Selection](#23-model-catalog--selection)
   - [2.4 Working with Attachments (Images, Code, PDFs)](#24-working-with-attachments-images-code-pdfs)
   - [2.5 Using the Interactive Web Terminal (ttyd)](#25-using-the-interactive-web-terminal-ttyd)
3. [Administrator & Operator Manual](#3-administrator--operator-manual)
   - [3.1 Cluster Deployment Topology](#31-cluster-deployment-topology)
   - [3.2 Storage Layout & Mount Invariants](#32-storage-layout--mount-invariants)
   - [3.3 Zero-Data-Loss Persistence Lifecycle (PreStop Hook)](#33-zero-data-loss-persistence-lifecycle-prestop-hook)
   - [3.4 Dynamic Application Reverse Proxy Gateway](#34-dynamic-application-reverse-proxy-gateway)
   - [3.5 Supervised Artifact & Data Quality Servers (Ports 8099 & 8899)](#35-supervised-artifact--data-quality-servers-ports-8099--8899)
4. [Self-Healing & Resilience Subsystems](#4-self-healing--resilience-subsystems)
   - [4.1 Attachment Crash Immunity (Layer 10 & 11)](#41-attachment-crash-immunity-layer-10--11)
   - [4.2 Stale Session Lock Cleanser](#42-stale-session-lock-cleanser)
   - [4.3 Model Clamping & Gateway Fallback](#43-model-clamping--gateway-fallback)
   - [4.4 Dynamic Context Window Clamping & Auto-Compaction](#44-dynamic-context-window-clamping--auto-compaction)
5. [Troubleshooting & Diagnostic Runbook](#5-troubleshooting--diagnostic-runbook)
   - [Case 1: "This turn failed Attachment object is missing"](#case-1-this-turn-failed-attachment-object-is-missing)
   - [Case 2: Session is Locked / Read-Only After Pod Crash](#case-2-session-is-locked--read-only-after-pod-crash)
   - [Case 3: Ingress Returns HTTP 502 Bad Gateway](#case-3-ingress-returns-http-502-bad-gateway)
   - [Case 4: Dynamic Proxy Port Returns 404 or Refused](#case-4-dynamic-proxy-port-returns-404-or-refused)
   - [Case 5: CIFS Mount Fails or Reports Read-Only Filesystem](#case-5-cifs-mount-fails-or-reports-read-only-filesystem)
   - [Case 6: Model Selection Reverts or Shows Loading Indefinitely](#case-6-model-selection-reverts-or-shows-loading-indefinitely)
   - [Case 7: Custom CA Certificate SSL Verification Failures](#case-7-custom-ca-certificate-ssl-verification-failures)
   - [Case 8: Missing History After Pod Redeploy](#case-8-missing-history-after-pod-redeploy)
   - [Case 9: Context Window Exceeded (HTTP 400 During Long Turns or Compaction)](#case-9-context-window-exceeded-http-400-during-long-turns-or-compaction)
6. [Maintenance & Routine Operations](#6-maintenance--routine-operations)
   - [6.1 Zero-Downtime Rolling Restarts](#61-zero-downtime-rolling-restarts)
   - [6.2 Manual Data Synchronization Trigger](#62-manual-data-synchronization-trigger)
   - [6.3 Upgrading DSH Upstream Version](#63-upgrading-dsh-upstream-version)
   - [6.4 Backup & Disaster Recovery](#64-backup--disaster-recovery)

---

## 1. Architecture & System Topology

DeepSeek Harness (DSH) is deployed inside the Kubernetes namespace `llm` behind an Ingress-Nginx controller:

```
                            HTTPS Inbound (Internet / Intranet)
                                           │
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ Ingress-Nginx: https://dsh.aiportal.bot.or.th/ & *.dsh.aiportal.bot.or.th               │
└──────────────────────────────────────────┬─────────────────────────────────────────────┘
                                           │ Port 3080
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ Pod: dsh-xxxxxxxxx (Namespace: llm)                                                    │
│                                                                                        │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ 🔐 Enterprise Auth Proxy (Port 3080)                                              │  │
│  │   • Cookie Auth Verification (`dsh_auth`)                                        │  │
│  │   • Dynamic Reverse Proxy (/proxy/<port>/ and <subdomain>-<port>)                │  │
│  │   • Automatic Launch Token Injection into Upstream DSH                           │  │
│  └──────────────┬────────────────────────┬──────────────────────┬───────────────────┘  │
│                 │                        │                      │                      │
│     Forward to  │ Port 3081              │ Port 7681            │ Ports 8099 / 8899    │
│     127.0.0.1   ▼                        ▼                      ▼                      │
│  ┌────────────────────────┐  ┌───────────────────────┐  ┌───────────────────────────┐  │
│  │ 🤖 DSH Engine          │  │ 🖥️ Web Terminal (ttyd)│  │ 📊 Supervised DQ Servers  │  │
│  │   • Node 22 + Ubuntu   │  │   • Port 7681         │  │   • Port 8099: Static DQ  │  │
│  │   • LiteLLM Integration│  │   • bash -l           │  │   • Port 8899: Supervised │  │
│  │   • Local Fast Storage │  │   • Zero-Trust Cookie │  │   • Python http.server    │  │
│  └────────────────────────┘  └───────────────────────┘  └───────────────────────────┘  │
│                 │                                                                      │
│                 │ Continuous Sync (15s Loop) + PreStop Hook (Synchronous Final Flush) │
│                 ▼                                                                      │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ 💾 Persistent CIFS / SMB Storage (/workspace -> da-workspace-pvc-new)            │  │
│  │   • sessions/ (all historical chats)                                             │  │
│  │   • storages/ (extension metadata & project caches)                              │  │
│  │   • attachments/ (uploaded images & documents)                                   │  │
│  │   • workspaces/ (per-user development home roots)                                │  │
│  │   • .credentials.yaml (authenticated provider tokens)                            │  │
│  └──────────────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. End-User Operating Manual

### 2.1 Access & Web Authentication
1. Navigate in any modern web browser to: **`https://dsh.aiportal.bot.or.th/`**
2. If you are not authenticated, you will be redirected to `/login`:
   - **Sign In**: Enter your assigned username and password.
   - **Create Account**: Click "Create an account" to self-provision a fresh workspace.
   - **Change Password**: Change your password at any time via the login portal.
3. Upon authentication, a secure HTTP-only cookie (`dsh_auth`) is issued for the authority `dsh.aiportal.bot.or.th`.

### 2.2 Session Management & Workspaces
- **New Session**: Click the `+` button in the left sidebar to start a new chat.
- **Switching Workspaces**: Use the workspace directory selector at the top-left of the DSH interface. Workspaces are automatically mapped to your persistent directory `/workspace/users/<username>/`.
- **Search & History**: Past sessions are preserved in the sidebar. Sessions are automatically persisted every 15 seconds and on container restart.

### 2.3 Model Catalog & Selection
- DSH comes pre-configured with the Bank's in-cluster LLM models:
  - **`litellm-cluster/deepseek-v4.1-flash`** *(Default)*: effective 131,072-token context window and 8,192-token maximum output through the current DSH route.
  - **`litellm-cluster/deepseek-flash`**: High-speed, lightweight conversational model.
  - **`litellm-cluster/glm-5.3-flash`**: Enterprise multilingual reasoning model.
  - **`litellm-cluster/qwen3.8-27b`**: 27B parameter instruction-tuned model.
- Model selections are stored in your user profile and persist across browser reloads.

### 2.4 Working with Attachments (Images, Code, PDFs)
- **Drag-and-Drop / Paste**: You can paste screenshots directly from the clipboard (`Ctrl+V`) or drag files into the chat bar.
- **Self-Healing Attachments**: If an image file was stored on older temporary storage and became inaccessible on disk, the system automatically detects this and supplies a clean placeholder rather than failing the conversation turn.

### 2.5 Using the Interactive Web Terminal (ttyd)
- Access the interactive terminal directly in your browser:
  - **URL**: `https://dsh.aiportal.bot.or.th/proxy/terminal/` (or port `7681`).
- Spawns a full bash terminal with tools: `python3`, `git`, `curl`, `jq`, `socat`, `build-essential`.

---

## 3. Administrator & Operator Manual

### 3.1 Cluster Deployment Topology
- **Namespace**: `llm`
- **Deployment**: `deployment/dsh`
- **ConfigMap**: `configmap/dsh-scripts` (mounts `/scripts/auth_proxy.js` and `/scripts/configure_models.js`)
- **PVC**: `da-workspace-pvc-new` mounted at `/workspace` with `subPath: dsh`

### 3.2 Storage Layout & Mount Invariants
To prevent SMB/CIFS file-locking crashes (`EACCES: permission denied, lock failed` on SQLite and LevelDB):
1. **Local Rootfs Fast Tier (`/root/.dsh/`)**:
   - `sessions/`, `storages/`, and `attachments/` run directly on container local ext4/overlayfs.
   - Provides zero-latency locking and POSIX compliance.
2. **Persistent Cold Tier (`/workspace/dsh_storage/`)**:
   - Non-volatile SMB/CIFS mount.
   - Houses backups of `sessions/`, `storages/`, `attachments/`, `workspaces/`, and `.credentials.yaml`.

### 3.3 Zero-Data-Loss Persistence Lifecycle (PreStop Hook)
To prevent data loss when pods are terminated (e.g. during redeployments or Kubernetes upgrades):
1. **15-Second Background Daemon**:
   - Copies modified files from `/root/.dsh/` to `/workspace/dsh_storage/` every 15 seconds.
2. **Synchronous `preStop` Lifecycle Hook**:
   - Kubernetes runs `preStop` **before** sending `SIGTERM` to the container.
   - Synchronously executes:
     ```bash
     cp -ru /root/.dsh/sessions/. /workspace/dsh_storage/sessions/
     find /workspace/dsh_storage/sessions -name "session.lock" -delete
     cp -ru /root/.dsh/storages/. /workspace/dsh_storage/storages/
     cp -ru /root/.dsh/attachments/. /workspace/dsh_storage/attachments/
     cp -u /root/.dsh/.credentials.yaml /workspace/dsh_storage/.credentials.yaml
     sync
     ```
   - `terminationGracePeriodSeconds: 60` provides up to 60 seconds for the CIFS writes to complete.
3. **Container Bootstrap Restoration**:
   - On container boot, all files from `/workspace/dsh_storage/` are restored to `/root/.dsh/`, and stale `session.lock` files are purged.

### 3.4 Dynamic Application Reverse Proxy Gateway
The auth proxy on port 3080 dynamically forwards traffic to any port running inside the pod:
- **Path-Based**: `https://dsh.aiportal.bot.or.th/proxy/<port>/` (e.g. `/proxy/8501/` for Streamlit).
- **Subdomain-Based**: `https://dsh-<port>.aiportal.bot.or.th/`.
- **WebSocket / SSE**: Supports live HTTP `Upgrade` for Streamlit, Vite HMR, and Jupyter.

### 3.5 Supervised Artifact & Data Quality Servers (Ports 8099 & 8899)
The container startup script automatically launches persistent HTTP servers for static deliverables:
- **Port 8099**: Serves `/workspace/dsh_storage/docs/` (or `/root/docs/`).
- **Port 8899**: Supervised Python server serving project reports.
- **Access URLs**:
  - `https://dsh.aiportal.bot.or.th/proxy/8099/dq_report.html`
  - `https://dsh.aiportal.bot.or.th/proxy/8899/dq_report.html`

### 3.6 Deployment Readiness and Context-Limit Invariants
- The DSH containers install runtime packages before starting the internal engine on port 3081. Kubernetes must not publish a replacement pod during this bootstrap interval.
- Each DSH manifest therefore uses a TCP readiness probe against the named `dsh-web` port (3081). For the primary `dsh` RollingUpdate, this keeps the previous pod serving until the replacement engine is listening.
- `dsh-user2` and `dsh3` currently use the `Recreate` strategy. Their probes prevent premature endpoint publication but do not provide zero-downtime replacement.
- The active request path is `DSH -> LiteLLM -> service/vllm-deepseek-v4-flash -> deployment/vllm-deepseek-v4-1-flash (SGLang)`. The backend is configured for 1,048,576 total tokens after progressive testing; LiteLLM and DSH retain a 131,072-token user budget and 8,192-token output ceiling. See [the complete optimization record](CONTEXT_OPTIMIZATION_20261015.md).
- SGLang keeps `max-running-requests=16`; this is a scheduler ceiling, not a reservation of 1M tokens for every request. The shared cache pool determines simultaneous capacity. The final static-0.90/chunk-1024 startup reported 1,179,648 aggregate slots. The historical 2,185,984-slot count at static 0.92 did not account for temporary workspace and was followed by an OOM. Neither count proves two full 1M requests can execute.
- Two maximum-length requests therefore fit concurrently. Shorter requests continue in parallel while their combined input, cached prefix, and generated output remain within the shared pool; additional work queues under the FCFS scheduler.

---

## 4. Self-Healing & Resilience Subsystems

### 4.1 Attachment Crash Immunity (Layer 10 & 11)
- **Problem**: When historical attachments referenced in a chat session are missing from disk (`ENOENT`), upstream DSH throws `AttachmentError("Attachment object is missing.")`, crashing the turn permanently.
- **Remediation**:
  - **Section 10 (`dsh-llm-pi-ai`)**: Intercepts missing attachments during LLM context assembly and substitutes a textual placeholder notice (`[image omitted: attachment not found on host]`).
  - **Section 11 (`dsh-attachment-local`)**: Patches `readImageFile`. When `ENOENT` occurs, generates and returns a synthetic 1x1 transparent PNG. Thumbnail rendering in `dsh-api-session-controller` and turn execution succeed without throwing exceptions.

### 4.2 Stale Session Lock Cleanser
- **Problem**: If a pod crashes abruptly, SQLite/Cordis `session.lock` files left on disk prevent the session from being edited after pod recreation.
- **Remediation**: On pod boot and inside the `preStop` hook, `find /root/.dsh/sessions -name "session.lock" -delete` automatically removes all dead locks.

### 4.3 Model Clamping & Gateway Fallback
- Model token limits (`max_tokens`) are clamped dynamically in `configure_models.js` to match the in-cluster LiteLLM gateway ceilings, preventing HTTP 400 Bad Request errors.

### 4.4 Dynamic Context Window Clamping & Auto-Compaction
- **Problem**: Input tokens, retained tool results, and requested completion tokens share one context budget. A request fails when their total exceeds the active engine limit.
- **LiteLLM Gateway Layer (`DynamicContextClamper`)**:
  - Implemented custom pre-call hook `custom_callbacks.py` in ConfigMap `litellm-config` inheriting from `CustomLogger`.
  - Dynamically calculates exact available headroom: `available_output = 131072 - input_tokens - 256`.
  - Automatically clamps every request to `max_tokens = min(requested, 8192, available_output)`.
  - Rejects requests whose input alone has consumed the safe context budget with an instruction to compact or start a new session; it never creates a knowingly invalid request.
- **DSH Client Layer (`compaction-basic`)**:
  - Configured in `/root/.dsh/profiles/web/cordis.patch.yml` with `thresholdRatio: 0.75`; the selected model supplies `contextWindow: 131072`.
  - At approximately 75% of the current 131,072-token user window (98,304 tokens), DSH triggers autonomous background compaction (`/compact`) to preserve output and tool-call headroom.
  - The model selector displays the resolved catalog model. While the catalog is loading it displays the loading state; if no model resolves it displays `Model unavailable` rather than a hardcoded model name.

---

## 5. Troubleshooting & Diagnostic Runbook

### Case 1: "This turn failed Attachment object is missing"
- **Symptom**: Red error text under a chat turn stating `• This turn failed Attachment object is missing.`
- **Cause**: An image or document uploaded in an earlier turn cannot be found on disk.
- **Diagnostic**:
  ```bash
  kubectl logs -n llm deployment/dsh -c dsh --tail=100 | grep -E "ATTACHMENT|Image"
  ```
- **Resolution**:
  - The latest `configmap/dsh-scripts` contains Section 11 synthetic fallback.
  - Verify that the patch was applied during boot:
    ```bash
    kubectl logs -n llm deployment/dsh -c dsh | grep -i "synthetic fallback"
    ```
    Output should show: `[CONFIG] Patched dsh-attachment-local readImageFile with synthetic fallback`.

---

### Case 2: Session is Locked / Read-Only After Pod Crash
- **Symptom**: Chat interface says "Session is locked by another process".
- **Resolution**:
  Exec into the pod and clear locks:
  ```bash
  kubectl exec -n llm deployment/dsh -c dsh -- find /root/.dsh/sessions -name "session.lock" -delete
  ```

---

### Case 3: Ingress Returns HTTP 502 Bad Gateway
- **Symptom**: Browser displays `502 Bad Gateway` from Nginx.
- **Diagnostic**:
  1. Check if the DSH pod is running:
     ```bash
     kubectl get pods -n llm -l app=dsh
     ```
  2. Check if the internal ports are listening:
     ```bash
     kubectl exec -n llm deployment/dsh -c dsh -- ss -tulpn
     ```
     Ensure port 3080 (`auth_proxy.js`) and port 3081 (`dsh web`) are in `LISTEN` state.
  3. Inspect pod restart logs:
     ```bash
     kubectl logs -n llm deployment/dsh -c dsh --previous
     ```

---

### Case 4: Dynamic Proxy Port Returns 404 or Refused
- **Symptom**: Accessing `https://dsh.aiportal.bot.or.th/proxy/8099/` returns `ECONNREFUSED` or `404 Not Found`.
- **Diagnostic**:
  Check if the target port has an active listening process inside the pod:
  ```bash
  kubectl exec -n llm deployment/dsh -c dsh -- ss -tulpn | grep 8099
  ```
- **Resolution**:
  If the process died, start it or trigger the background supervisor:
  ```bash
  kubectl exec -n llm deployment/dsh -c dsh -- bash -c "nohup python3 -m http.server 8099 --directory /workspace/dsh_storage/docs >/dev/null 2>&1 &"
  ```

---

### Case 5: CIFS Mount Fails or Reports Read-Only Filesystem
- **Symptom**: Background sync logs show `Read-only file system` or `Permission denied` on `/workspace`.
- **Resolution**:
  1. Verify the mount status:
     ```bash
     kubectl exec -n llm deployment/dsh -c dsh -- df -h /workspace
     ```
  2. Test writability:
     ```bash
     kubectl exec -n llm deployment/dsh -c dsh -- touch /workspace/dsh_storage/.writetest && rm -f /workspace/dsh_storage/.writetest
     ```
  3. If CIFS is locked by storage cluster failover, remount or point `claimName` to `da-workspace-pvc-new`.

---

### Case 6: Model Selection Reverts or Shows Loading Indefinitely
- **Symptom**: Model dropdown stays on "Loading models..." or switches unexpectedly.
- **Resolution**:
  Verify Section 4 & 5 patches in `configure_models.js`:
  ```bash
  kubectl logs -n llm deployment/dsh -c dsh | grep -i "client-ui-model-selection"
  ```
  Ensure `/root/.dsh/settings.yaml` contains:
  ```yaml
  model: litellm-cluster/deepseek-v4.1-flash
  ```

---

### Case 7: Custom CA Certificate SSL Verification Failures
- **Symptom**: Python or Node.js requests fail with `UNABLE_TO_VERIFY_LEAF_SIGNATURE` or `SSL: CERTIFICATE_VERIFY_FAILED`.
- **Resolution**:
  Inspect `/usr/local/share/ca-certificates/` and update system bundles:
  ```bash
  kubectl exec -n llm deployment/dsh -c dsh -- update-ca-certificates --fresh
  ```

---

### Case 8: Missing History After Pod Redeploy
- **Symptom**: Chat sessions appear empty after a redeployment.
- **Resolution**:
  1. Check if backup sessions exist on CIFS:
     ```bash
     kubectl exec -n llm deployment/dsh -c dsh -- ls -la /workspace/dsh_storage/sessions/
     ```
  2. Manually restore them to local storage:
     ```bash
     kubectl exec -n llm deployment/dsh -c dsh -- cp -ru /workspace/dsh_storage/sessions/. /root/.dsh/sessions/
     ```
  3. Clear locks and restart DSH:
     ```bash
     kubectl exec -n llm deployment/dsh -c dsh -- find /root/.dsh/sessions -name "session.lock" -delete
     ```

---

---

### Case 9: Context Window Exceeded (HTTP 400 During Long Turns or Compaction)
- **Symptom**: Chat turn or manual `/compact` fails with:
  `This turn failed 400: ... Requested token count exceeds the model's maximum context length ...`
- **Root Cause**:
  The combined input and requested completion exceed the engine's configured 131,072-token window, or one layer still advertises a stale limit.
- **Diagnostic**:
  1. Inspect LiteLLM custom callback status:
     ```bash
     kubectl logs -n llm deployment/litellm -c litellm --tail=50 | grep -i "DynamicContextClamper"
     ```
  2. Test completion headroom directly from cluster:
     ```bash
     kubectl exec -n llm deployment/dsh -c dsh -- python3 -c '
     import urllib.request, json
     payload = {"model": "deepseek-flash", "messages": [{"role": "user", "content": "hi " * 30000}], "max_tokens": 65536}
     req = urllib.request.Request("http://litellm.llm.svc.cluster.local:4000/v1/chat/completions",
         data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "Authorization": "Bearer sk-1234"})
     try:
         res = urllib.request.urlopen(req)
         print("OK:", res.status)
     except Exception as e:
         print("ERR:", e)
     '
     ```
- **Resolution**:
  1. Ensure `litellm-config` ConfigMap in namespace `llm` has `custom_callbacks.py` (`DynamicContextClamper`) mounted and registered in `litellm_settings.callbacks`.
  2. Ensure `model_info.max_output_tokens` is configured to `8192` in `litellm-config`.
  3. Ensure `/root/.dsh/profiles/web/cordis.patch.yml` and `/root/.dsh/settings.yaml` specify `contextWindow: 131072` and `maxTokens: 8192`.
  4. Run `/compact` in the active session to summarize older turns down to ~2,000 tokens.

---

## 6. Maintenance & Routine Operations

### 6.1 Zero-Downtime Rolling Restarts
To safely restart DSH without data loss:
```bash
kubectl rollout restart deployment/dsh -n llm
kubectl rollout status deployment/dsh -n llm
```
*The `preStop` hook attempts a legacy CIFS flush; it is not a zero-loss guarantee and is absent from the new pools.*

### 6.2 Manual Data Synchronization Trigger
To trigger an immediate forced sync from local memory/rootfs to CIFS storage:
```bash
kubectl exec -n llm deployment/dsh -c dsh -- bash -c "
  cp -ru /root/.dsh/sessions/. /workspace/dsh_storage/sessions/ 2>/dev/null || true
  cp -ru /root/.dsh/storages/. /workspace/dsh_storage/storages/ 2>/dev/null || true
  cp -ru /root/.dsh/attachments/. /workspace/dsh_storage/attachments/ 2>/dev/null || true
  cp -u /root/.dsh/.credentials.yaml /workspace/dsh_storage/.credentials.yaml 2>/dev/null || true
  sync
  echo 'Manual sync complete.'
"
```

### 6.3 Upgrading DSH Upstream Version
1. Check the latest stable release on npm:
   ```bash
   npm view @deepseek-ai/dsh dist-tags
   ```
2. Update the version pin in `k8s/deployment.yaml` (`npm install -g @deepseek-ai/dsh@<new-version>`).
3. Commit, push to GitHub, and run `kubectl apply -f k8s/deployment.yaml -n llm`.

### 6.4 Backup & Disaster Recovery
To create an offline tarball backup of all users, chats, and configurations:
```bash
kubectl exec -n llm deployment/dsh -c dsh -- tar -czf /workspace/dsh_backup_$(date +%Y%m%d_%H%M%S).tar.gz -C /workspace dsh_storage users
```
To restore:
```bash
kubectl exec -n llm deployment/dsh -c dsh -- tar -xzf /workspace/<backup_file>.tar.gz -C /workspace
```

## Shared-model scheduling validation

The model's `interactive-v2` overlay is maintained in GPU_server, not in the DSH package overlay. It matches queued cache prefixes before reserving up to 512 prefill tokens, retains long-request progress, and uses mixed chunking plus a decode interval of four. The first revision passed tiny prompts but failed cached 24K sessions; V2 passed both. See [the full scheduling record](SCHEDULING_FAIRNESS_20261015.md).

Before changing either the model image or client prompt construction, repeat the fresh-input and continuing-session interference gates. Preserve the original scheduler source-hash check and review it against the next image; do not blindly rebase or accept a new hash. The present 128K client guardrail remains in force. Large uncached history can still queue, and near-1M mixed-load behavior has not been revalidated.


## Runtime rollout verified — 15 October 2026, 20:39 ICT

Build 62702 is deployed in gateway, Secure and Internet. Read the [actual rollout procedure, restart/persistence results and rollback limitations](DSH_RDT_PILOT_SECURITY_CONTROL_ASSESSMENT.md#safe-runtime-rollout--actual-deployed-result) and [live evidence](context-evidence/runtime-rollout-live-20261015.json). Secure retained 80 listed histories and 2,732 checked files; Internet retained controlled markers. Coherent local snapshot PVCs were retained; no central DA_WORKSPACE synchronization or full restore was established. Use Recreate and actual application health probes; do not run two state writers or co-mount live state in a verifier pod. The GPU configuration was not changed by this rollout.
