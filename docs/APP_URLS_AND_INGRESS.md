# Application URLs, login destinations and port publishing

## Choose what to open

On the login page choose **DSH workspace**, **Web Terminal** or **JupyterLab** from **Open after sign in**. DSH is the default. The separate environment selector still defaults to No Internet. Choosing an application never grants Internet access or changes your private runtime.

| Choice | Browser route | Private application |
|---|---|---|
| DSH | `/` | DSH web workspace |
| Web Terminal | `/terminal` → `/proxy/terminal/` | Terminal on port 7681 |
| JupyterLab | `/proxy/8888/lab` | Notebook server on port 8888 |
| My application URLs | `/applications` | Create, check and remove your app names |

JupyterLab is installed. If stopped, open Web Terminal and run `jupyter lab`, then reopen JupyterLab. Selecting an application does not execute shell commands automatically. Stopping its process does not delete saved notebooks.

## Custom URL for a custom port

1. Sign in to the desired environment and open `/applications`.
2. Enter a name and your application's listening port. The suggestion is `<username>-jupyter`, port `8888`. For a different app use, for example, `alice-report`, port `8501`.
3. Wait for the form to finish loading, then select **Check name** and **Save URL**. These controls stay disabled until your authenticated app settings are ready.
4. Start the application in that same environment and open its saved link.

`alice-report` → port `8501` produces `/proxy/alice-report/`. The gateway strips that prefix and forwards the remaining path, query, HTTP methods and WebSocket to port 8501 in Alice's selected runtime. Users cannot supply a destination machine, IP or Service. Another user cannot reserve or open Alice's saved name. An alias can have different ports in the owner's two environments; a missing environment mapping is refused.

Names use 3–63 lowercase letters, digits and hyphens. Built-in names and management ports are reserved. Each account can hold 64 named URLs. Removing a URL removes its mapping, not its files or running process. Mappings are atomically saved in a protected gateway auth-volume file, separately from passwords and histories.

Jupyter's friendly link redirects to `/proxy/8888/lab`: its managed assets, APIs, kernels and XSRF/origin checks retain a fixed base URL. Other apps must support their browser-visible path, or use an approved hostname. A proxy cannot automatically repair every framework's redirects, absolute asset URLs or cookie paths.

## Administrator visibility and capacity planning

The deployed limit is **64 names per user across both environments**, with **4,096 names overall**. The current admin dashboard shows app save/delete audit events, but cannot yet list or edit every user's mappings or change these limits. The app-name limit is fixed in gateway code; it is not an editable account setting today.

For the current deployment, the recommended next release is **8 names by default**, increases to **16** through administrator approval, a **64-name hard ceiling** and a **256-name site cap**. These proposed values are not active. A path and hostname for one alias count as one name, and that alias may have one port per environment. Names are routing metadata, not reserved compute capacity.

The proposed Applications tab will list owner, name, both environment ports, enabled state and usage/limit, and allow authorized mapping changes and quota overrides. Lowering a quota must preserve existing mappings; it only prevents additional names. Removing a mapping must preserve application files and running processes. See [admin application management and acceptance plan](ADMIN_USAGE_TELEMETRY.html).

## Paths and custom hostnames

| Style | Example | Requirements |
|---|---|---|
| Same DSH address | `https://dsh.example.internal/proxy/alice-report/` | Saved mapping and listening app; no extra DNS or Ingress |
| Custom hostname | `https://alice-report.apps.example.internal/` | Mapping, approved gateway `DSH_APP_DOMAIN`, DNS, TLS and an Ingress to the authentication gateway |

The suggested notebook hostname label is `<username>-jupyter`. Dots/underscores in a username become hyphens; check for collisions. Users choose a name and local port, not arbitrary domains, cluster Services, certificates or other runtimes.

**Both styles use the same saved app name and private port.** After the operator installs the wildcard DNS, TLS and authenticated wildcard route, users choose an available prefix and the hostname works dynamically. Saving an app does not create a new Kubernetes object or allocate an arbitrary external domain. The site suffix is operator configuration; public installations can use `apps.example.com`, `xxx.example.com` or another approved domain.

An independent inventory reader refreshes existing Ingress rules and NGINX server-alias reservations every 15 seconds. Kubernetes propagates its read-only ConfigMap to the gateway asynchronously. The gateway rejects new hostname claims when inventory is older than three minutes or unavailable; existing custom path URLs continue to work. Existing exact-host sites take precedence over the wildcard route, and their names cannot be claimed through the app form. A name check is an observation, not a global DNS reservation against future infrastructure changes.

The gateway checks hostname ownership and environment before forwarding. After sign-in, unowned/unknown app names are refused. Login, My apps and Web Terminal navigation from an app hostname return to the canonical DSH address, so the selected tool cannot be mistaken for the app running on that hostname. Ordinary apps can remain at their hostname if compatible with that Host/Origin. Jupyter hostname links redirect to the canonical notebook path. Do not publish a direct unauthenticated worker Ingress.

## Check name and Ingress availability

The browser checks the protected DSH registry and, when automatic hostnames are enabled, the fresh cluster Ingress reservations. It does not allocate a DNS zone. For an alternative manually published exact hostname, the operator can inspect all visible Ingress rules:

```sh
python scripts/plan_app_ingress.py \
  --user alice --name alice-report --domain apps.example.internal \
  --namespace llm --service dsh-environment-gateway \
  --tls-secret dsh-apps-tls --output /private/alice-report-ingress.yaml
```

Omit `--name` to suggest `alice-jupyter`. The command reads all namespaces, refuses exact-host or matching single-label wildcard conflicts and checks the deterministic Ingress resource name. Missing read permission is a failure, not proof of availability. `--inventory /private/ingresses.json` accepts an operator export; verify its freshness.

DNS resolution is reported separately. Wildcard DNS may resolve an unused name without reserving it or establishing certificate coverage. The command renders a candidate only. Availability is a point-in-time observation, not an atomic global reservation; recheck before applying and use one operator/controller as publisher.

## Operator automatic-hostname setup

The domain is configurable. No internal site value or credential is required in the public repository. Copy `config/app-hostnames.example.json` to a private operator file and supply the namespace, domain, authenticated gateway Service, TLS Secret, immutable runtime image and explicit Kubernetes API addresses. The example image/destinations are placeholders.

```sh
python scripts/render_app_hostname_support.py \
  --settings /private/app-hostnames.json \
  --output /private/app-hostnames.yaml
kubectl apply --dry-run=server -f /private/app-hostnames.yaml
```

The renderer supplies a wildcard Ingress plus a separate inventory workload. The inventory identity can only read Ingress metadata and update its one named ConfigMap. It cannot read Secrets, accounts, pods, user data or other ConfigMaps, and cannot create/edit/delete Ingresses or workloads. Its network rule permits only the explicit Kubernetes API addresses. The authentication gateway and all execution workers retain no Kubernetes management token. Verify authorization using the reader's actual service-account token, not solely an impersonation check through an authentication proxy.

Install and qualify the inventory workload first; keep the wildcard Ingress last for controlled activation. Mount `dsh-app-host-inventory` read-only at `/app-host-inventory` in the gateway, set `DSH_APP_DOMAIN` and `DSH_APP_INVENTORY_FILE=/app-host-inventory/inventory.json`, and verify that the reserved list is fresh. `scripts/rollout_admin_management.py` supports `--app-domain` and `--app-inventory-configmap`; its source-hash and signup-acceptance gates remain required. Preserve its rollback snapshot. Check all prerequisites below before applying the final wildcard Ingress.

1. Obtain an approved app-only DNS domain or explicitly allocated hostnames. Avoid a catch-all on a shared organizational domain.
2. Point the approved names/wildcard at the ingress controller. Use a trusted certificate whose SAN covers those names and a TLS Secret in the Ingress namespace.
3. Set the approved domain on the gateway and keep `DSH_TRUSTED_HOST` fixed to the canonical DSH site. Configure `DSH_COOKIE_DOMAIN` to a parent shared by that site and the approved app names, or use the default canonical-host parent. For example, `dsh.example.internal` and `NAME.apps.example.internal` share `example.internal`. Unrelated domains do not share a browser login cookie. Ordinary user forms cannot change these settings.
4. Review and install the generated wildcard route after the gateway and inventory are qualified. Users can then save their names and ports without another operator deployment. For the optional exact-host method only, run:

```sh
kubectl apply --dry-run=server -f /private/alice-report-ingress.yaml
kubectl apply -f /private/alice-report-ingress.yaml
```

5. The wildcard routes `*.apps.example.internal` to the authentication gateway. Kubernetes wildcards match one DNS label. DNS, certificate and Ingress wildcards are three separate settings. Exact-host services keep their routes; the inventory reserves their names. Reject a conflicting existing wildcard instead of replacing it.
6. Disable response buffering, support WebSockets, preserve original Host/Origin through the trusted ingress, deliberately set body/timeout limits and overwrite untrusted forwarded headers. Existing private-worker network policies continue to apply.
7. Verify normal TLS, anonymous and wrong-user denial, environment approval/revocation, assets, uploads, redirects, terminal/kernel WebSockets and persistence.

Users and prompts do not edit Ingress objects. Dynamic publication consists of a user-owned alias/port mapping under the installed wildcard route. The reader maintains reservations, not per-app routes. Revert the wildcard/gateway configuration on regression and retain the canonical site/path proxy; never overwrite newer account, workspace, app mapping or history content.

References: [Kubernetes Ingress wildcards](https://kubernetes.io/docs/concepts/services-networking/ingress/#hostname-wildcards), [NGINX exact-name and wildcard priority](https://nginx.org/en/docs/http/server_names.html), [Jupyter base URLs](https://jupyter-server.readthedocs.io/en/latest/operators/public-server.html#running-the-notebook-with-a-customized-url-prefix).
