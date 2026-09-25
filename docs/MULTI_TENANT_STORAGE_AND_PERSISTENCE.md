# Multi-Tenant Workspaces & Storage Persistence Guide

This deployment of DeepSeek Harness (DSH) provides enterprise-grade multi-tenant workspace isolation and non-volatile storage persistence across container recreations and node reboots.

---

## 🏛️ Filesystem Layout

```
/ (Container Rootfs)
├── root/
│   ├── .dsh/
│   │   ├── settings.yaml            # Pre-configured DSH runtime settings
│   │   ├── sessions/ -> symlink     # /workspace/dsh_storage/sessions
│   │   ├── storages/ -> symlink     # /workspace/dsh_storage/storages
│   │   └── .credentials.yaml        # Cloned from /workspace/dsh_storage
│   ├── users -> symlink             # /workspace/users
│   ├── workspace -> symlink         # /workspace
│   └── <username> -> symlink        # /workspace/dsh_storage/workspaces/<username>
└── workspace/ (Kubernetes PersistentVolumeClaim)
    ├── users/                       # Per-tenant user home folders
    │   ├── user1/                   # Isolated workspace for user1
    │   ├── user2/                   # Isolated workspace for user2
    │   └── .user_auth.json          # Salted SHA-256 hashed credentials
    ├── repos/                       # Cloned git repositories
    ├── dsh_storage/                 # Non-volatile DSH engine state
    │   ├── sessions/                # DSH chat sessions
    │   ├── storages/                # Cordis extension databases
    │   ├── workspaces/              # User workspace directories
    │   └── .credentials.yaml        # Persisted provider API credentials
    └── .ports.json                  # Named port aliases for dynamic gateway
```

---

## 🔒 Multi-Tenant User Isolation

1. **User Directories**:
   - Each registered user receives an isolated folder: `/workspace/users/<username>/`.
   - When a user logs in via the Web Login Gate (`/login`), the auth proxy resolves the session to that user's identity.

2. **Symlink Compatibility Layer**:
   - DSH often initiates file searches or workspace roots relative to `/root/` or `/workspace/`.
   - The container entrypoint creates automatic symlinks from `/workspace/dsh_storage/workspaces/<username>` to `/root/<username>` and `/workspace/users/<username>`.

3. **Background Persistence Watcher**:
   - A background synchronization loop runs inside the container every 10 seconds:
     - Copies `/root/.dsh/.credentials.yaml` back to `/workspace/dsh_storage/`.
     - Recursively synchronizes any user directories created directly under `/root/` back to the persistent volume at `/workspace/dsh_storage/workspaces/`.

---

## 💾 PersistentVolumeClaim (PVC) Configuration

To deploy on Kubernetes, provide a PersistentVolumeClaim mounted at `/workspace`:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: dsh-workspace-pvc
  namespace: llm
spec:
  accessModes:
    - ReadWriteOnce  # or ReadWriteMany if sharing across multiple worker pods
  resources:
    requests:
      storage: 50Gi
  storageClassName: standard  # adjust to your cluster's StorageClass
```

If sharing a large storage volume with other applications, use `subPath` in the pod volume mount:

```yaml
        volumeMounts:
        - name: shared-workspace-volume
          mountPath: /workspace
          subPath: dsh
```
