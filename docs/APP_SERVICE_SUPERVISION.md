# Managed Jupyter and application startup

## What starts automatically

An administrator can approve a JupyterLab server or a user application as a managed startup service. Saving a definition leaves a new service stopped. Editing an enabled definition applies its new approved command and restarts it; use Stop first if you want it held for a later Start. **Start** enables automatic startup, including after its worker pod is replaced. **Stop** disables it and stops its managed process group. **Restart** replaces the managed process; **Remove** removes the startup definition. These controls are separate from enabling or removing an application URL.

A saved notebook, script or data file lives in persistent workspace storage. A process, open kernel, Python variable or terminal job is memory, not durable data. Autostart creates a new server process; it does not restore an interrupted computation or an unsaved notebook. Save notebooks before maintenance.

## Architecture and user isolation

```mermaid
flowchart TB
 B[Authenticated browser] --> G[Authentication gateway and admin dashboard]
 G --> U[User A: No Internet pod]
 G --> I[User A: Internet pod]
 G --> V[User B: separate private pods]
 G --> C[Dedicated persistent service-control volume]
 C -->|Only this runtime's definitions: read-only| S
 subgraph U[User A: No Internet pod]
  D[DSH agent and web terminal container]
  S[Non-root service supervisor container]
  S --> J[JupyterLab and approved app processes]
  S --> T[Private runtime status PVC]
  T -->|Read-only| G
  D --> W[User A private workspace]
  J --> W
  J --> N[User A persistent notebook state]
 end
 D --> L[Shared internal LiteLLM]
 L --> GPU[Shared local GPU model]
```

The main platform assigns each user a private No Internet runtime and a separate private Internet runtime. A runtime is a Kubernetes pod managed by a Deployment. Its DSH agent, terminal and tools operate as a non-root identity. Different users do not share the same process or workspace mounts. The two environments have separate workspaces, histories, attachment storage and credential state. The expensive inference endpoint remains shared.

The supervisor is an additional container in the **same user/environment pod**. It shares that pod's network restrictions, CPU node and approved workspace, but has its own process namespace. It is not a second Internet route. It receives no GPU, Kubernetes management token, gateway account store or model API-key environment. Source code is mounted read-only, privilege escalation is disabled, capabilities are dropped and the root filesystem is read-only. A small temporary volume is provided for runtime files.

The supervisor mounts only the owner's existing workspace views, the owner's notebook-state subdirectory, approved package-cache views and its own service-control/status directories. Existing workspace masks remain in place. It does not mount the entire DSH history or credential directory. The gateway may change approved startup definitions; user code sees those definitions read-only. Startup definitions are stored separately from password records, app URL mappings and histories.

The per-runtime status PVC is separate from the shared policy volume and is read-only at the gateway. Status input is bounded; oversized or stale reports become unknown.

The current containers use non-root UID/GID 10001; a distinct Linux UID is not allocated to every account. Isolation therefore comes from the separate pod/container namespaces, private volume mounts, fixed authenticated routing and network policies, rather than from different directory names or UID numbers alone. Cluster and storage administrators remain trusted infrastructure operators.

No Internet workspaces and durable histories retain their existing central CIFS-backed mounts. Internet workspaces and histories remain separate. The notebook-state subdirectory stays on the original user's persistent state volume. The shared approved package cache is read-only; the Internet environment prepares incoming artifacts for reviewed promotion, rather than writing inside a protected workspace. The service installation does not move any of those files.

Platform passwords remain salted scrypt records in the gateway's protected account volume. Per-runtime launch tokens authenticate the internal proxy route; they are not user startup arguments. The DSH agent's own configured inference credentials stay in its existing user-scoped worker configuration. An agent with terminal/tool access can use that user's credentials and writable data; it does not receive another user's identity simply because the model suggested it. Applications must not be given admin passwords or credentials belonging to a different user.

This separates **users** and **environments**. It does not make an agent and all applications belonging to the same user mutually untrusted tenants. They can share and modify that user's approved workspace. An approved workspace script can change when its owner edits it. Approval grants permission to launch that script as that user; it is not a code-integrity signature or a stronger data entitlement.

## Permissions and credentials

| Component | Permission |
|---|---|
| Ordinary user | Uses their own DSH, terminal, notebooks, files and app URLs; cannot approve or edit startup definitions |
| Administrator | Chooses an existing owner/environment, approves startup definitions, starts/stops/restarts services and reviews status; this does not log admin into another user's app |
| DSH agent | Executes tools with its runtime identity and existing mounts; model suggestions do not elevate Linux, network, storage or datalake permissions |
| Supervisor and managed app | Runs non-root in the selected owner's environment, within the supervisor container resource limit |
| Gateway | Authenticates accounts, selects fixed provisioned destinations, writes protected control definitions and records lifecycle events; no Kubernetes management token |
| Infrastructure operator | Installs sidecars, mounts and policies and performs controlled rollouts; this remains privileged administration |

Local DSH credentials establish the platform login. A Kerberos principal is a separate user-specific identity. Its existing AD/datalake grants remain unchanged. The managed supervisor does not automatically inherit the agent's model keys, launch tokens, saved client profiles or Kerberos ticket cache. Authenticate a notebook/application through the user's approved mechanism when needed; never paste credentials into startup arguments, notebooks intended for sharing, reports or videos. A persistent notebook directory is not a credential vault.

Internet approval remains independent of startup approval. Managed Internet services are paused when the account is disabled or Internet approval is revoked; the gateway reconciles that permission and the supervisor applies it within a few seconds. Logout does not stop an explicitly approved background service. No Internet services retain the existing restricted-egress policy. Remote execution through other platforms retains those platforms' authorization and network boundaries.

## Admin workflow

1. Open **Admin overview → Managed startup services**.
2. Enter the exact existing owner and select No Internet or Internet.
3. For Jupyter, use service name **jupyter**, kind **Jupyter**, directory `/workspace`. Its authenticated port and root are fixed.
4. For a user app, first save its owned URL/port in Applications. Use the same service name, kind **Command**, a directory beneath `/workspace` and a JSON argv array, for example `["python3","app.py"]` or `["node","server.js"]`.
5. For a simple static preview, use `["python3","-m","http.server","8000","--bind","0.0.0.0"]` with a URL mapped to port 8000. A named npm script uses `["npm","run","dev"]`. Install dependencies beforehand through the appropriate approved workflow; startup does not install packages.
6. **Save definition**. A new definition is stopped. Review the selected owner and environment, then select **Start** and confirm.
7. Refresh to see supervisor-reported status. Open the user's authenticated Jupyter/app route through their own login to test it.
8. Use **Stop** before disabling a background workload, or **Restart** after a deliberate configuration change. Removing a URL alone does not remove its startup definition. Changing a URL port does not rewrite an approved command's arguments; update both deliberately.

Arguments are passed as an array, not a shell command. Supported executable forms are deliberately limited. The working directory and script must resolve beneath `/workspace`; symlink escapes are refused. There is no arbitrary destination host, Kubernetes command or credential editor. At most four managed services are permitted per environment. The existing per-user app-name quota remains separate.

A service that fails repeatedly uses exponential restart backoff capped at 60 seconds. If its requested port is already used, the supervisor reports the conflict and does not kill the unknown process. Invalid/unavailable control data stops managed services rather than using unreviewed settings. Status is supervisor-reported, with stale/missing reports shown as unknown. Output is not copied into the central dashboard or audit; credentials printed by an app must not become a central activity feed.

The stop operation targets the supervisor's managed process group. It is operational lifecycle management, not a universal sandbox for malicious code. Infrastructure termination of the container/pod remains the stronger containment action for deliberately escaping or uncooperative code.

## Installation and controlled rollout

1. Keep the existing pinned DSH runtime, authenticated gateway, private user routing, persistent workspace/state and network policies. No external package download is required during startup.
2. Prepare a private target file containing only reviewed `{user, mode, host}` rows. `mode` is `off` or `on`; hosts must be the existing private runtime destinations. Do not place credentials in this file or the public repository.
3. Render/review installation with the current pinned runtime image and a dedicated service-control PVC. The installer preserves existing application container settings and workspace masks, adds only the supervisor and its separate control mounts, and saves original deployment specifications privately.

```sh
python scripts/deploy_app_supervision.py \
  --gateway dsh-environment-gateway \
  --targets /private/service-targets.json \
  --control-pvc dsh-app-service-control \
  --output /private/supervision-plan
```

4. Qualify disposable users first: approved Jupyter and a real app must start automatically after pod replacement, retain saved notebook/data/settings, obey admin Stop, and reject ordinary-user control requests. Production installation requires the matching supervisor-source acceptance record.
5. Apply the reviewed installation with `--apply --acceptance /private/lifecycle-acceptance.json` to a new output directory. Use the existing idle-worker/persistence checks and perform a rolling handover. Adding a sidecar replaces a worker pod, so active memory-only computations need a maintenance handover.
6. The dedicated control PVC is mounted read/write only by the trusted gateway and through each runtime's individual read-only subdirectory. Do not mount the gateway auth volume in workers. Notebook state remains on the original user state volume. Each runtime has a separate small status PVC; only its supervisor writes it, and the gateway mounts it read-only. No worker writes on the shared control volume, so filling an own status volume cannot fill another user's policy store.
7. Publish the new gateway source only after its matching signup, authorization and persistence tests pass. Keep the saved gateway and worker specifications for rollback. Rollback removes startup functionality; it must never restore older workspace, history, notebook or account bytes.

The present file-based control store assumes one gateway writer and storage accessible to those pods on the current node. A multi-node deployment needs an appropriate shared storage class; a multi-replica gateway needs transactional control storage before enabling multiple writers. Destination FQDN and external GPU/LiteLLM placement remain operator configuration and do not require moving private workspaces to the GPU machine.
