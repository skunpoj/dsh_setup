# Multi-Tenant Workspaces & Storage Persistence Guide

This deployment of DeepSeek Harness (DSH) provides enterprise-grade multi-tenant workspace isolation and non-volatile storage persistence across container recreations and node reboots.

---

## 🏛️ Filesystem Layout & Storage Tiers

DSH uses a **two-tier decoupled storage architecture** to prevent SMB/CIFS lock failures while guaranteeing zero data loss:

```
/ (Container Rootfs - High Performance & POSIX Locking)
├── root/
│   ├── .dsh/
│   │   ├── settings.yaml            # Pre-configured DSH runtime settings
│   │   ├── sessions/                # Local rootfs session store (zero-latency locking)
│   │   ├── storages/                # Local rootfs extension DBs (resilient to CIFS locks)
│   │   ├── attachments/             # Local rootfs cached attachments & uploads
│   │   └── .credentials.yaml        # Cloned from /workspace/dsh_storage
│   ├── users -> symlink             # /workspace/users
│   ├── workspace -> symlink         # /workspace
│   └── <username> -> symlink        # /workspace/dsh_storage/workspaces/<username>
└── workspace/ (Kubernetes PersistentVolumeClaim - Non-Volatile CIFS/SMB)
    ├── users/                       # Per-tenant user home folders
    │   ├── user1/                   # Isolated workspace for user1
    │   ├── user2/                   # Isolated workspace for user2
    │   └── .user_auth.json          # Salted SHA-256 hashed credentials
    ├── repos/                       # Cloned git repositories
    ├── dsh_storage/                 # Non-volatile DSH engine state backup
    │   ├── sessions/                # DSH chat sessions backup
    │   ├── storages/                # Cordis extension databases backup
    │   ├── attachments/             # Non-volatile image/file attachment store
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

---

## 🛡️ Zero-Data-Loss Lifecycle Persistence

To prevent data loss during pod terminations (such as rolling updates, node drains, or Kubernetes redeployments), DSH uses a **two-tier synchronization system**:

### 1. Continuous Background Synchronization Loop
A background daemon runs every 15 seconds inside the pod:
- Mirrors `/root/.dsh/sessions/` to `/workspace/dsh_storage/sessions/`.
- Mirrors `/root/.dsh/storages/` to `/workspace/dsh_storage/storages/`.
- Mirrors `/root/.dsh/attachments/` to `/workspace/dsh_storage/attachments/`.
- Mirrors `/root/.dsh/.credentials.yaml` to `/workspace/dsh_storage/`.
- Purges any stale `session.lock` files on CIFS so they do not block subsequent boots.
- Recursively backs up active user folders created under `/root/` to `/workspace/dsh_storage/workspaces/`.

### 2. Synchronous Kubernetes `preStop` Lifecycle Hook
When Kubernetes initiates pod termination:
1. Kubernetes pauses and executes the container's `lifecycle.preStop` hook **first**, before sending `SIGTERM`.
2. The `preStop` script synchronously executes a final recursive copy of all active sessions, storages, attachments, and credentials to `/workspace/dsh_storage/`.
3. It cleans up all lock files and issues a Linux `sync` command to flush the SMB write cache.
4. `terminationGracePeriodSeconds: 60` gives the SMB cluster up to 60 seconds to commit all writes to disk.
5. Only after the `preStop` hook exits does Kubernetes terminate the container.

### 3. Bootstrap State Restoration
When a new container starts up:
1. It creates clean `/root/.dsh/sessions`, `/root/.dsh/storages`, and `/root/.dsh/attachments` directories on local rootfs.
2. It restores all past sessions, storages, and attachments from `/workspace/dsh_storage/`.
3. It strips any leftover `session.lock` files so all historical sessions are immediately writable.
4. It restores all user workspace symlinks into `/root/`.

---

## 💾 PersistentVolumeClaim (PVC) Configuration

To deploy on Kubernetes, provide a PersistentVolumeClaim mounted at `/workspace`:

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: da-workspace-pvc-new
  namespace: llm
spec:
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 100Gi
  storageClassName: cifs-storage
```

In the pod deployment manifest:

```yaml
        volumeMounts:
        - name: workspace-storage
          mountPath: /workspace
          subPath: dsh
      volumes:
      - name: workspace-storage
        persistentVolumeClaim:
          claimName: da-workspace-pvc-new
```
