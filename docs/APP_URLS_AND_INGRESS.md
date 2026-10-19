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
3. Select **Check name**, then **Save URL**.
4. Start the application in that same environment and open its saved link.

`alice-report` → port `8501` produces `/proxy/alice-report/`. The gateway strips that prefix and forwards the remaining path, query, HTTP methods and WebSocket to port 8501 in Alice's selected runtime. Users cannot supply a destination machine, IP or Service. Another user cannot reserve or open Alice's saved name. An alias can have different ports in the owner's two environments; a missing environment mapping is refused.

Names use 3–63 lowercase letters, digits and hyphens. Built-in names and management ports are reserved. Each account can hold 64 named URLs. Removing a URL removes its mapping, not its files or running process. Mappings are atomically saved in a protected gateway auth-volume file, separately from passwords and histories.

Jupyter's friendly link redirects to `/proxy/8888/lab`: its managed assets, APIs, kernels and XSRF/origin checks retain a fixed base URL. Other apps must support their browser-visible path, or use an approved hostname. A proxy cannot automatically repair every framework's redirects, absolute asset URLs or cookie paths.

## Paths and custom hostnames

| Style | Example | Requirements |
|---|---|---|
| Same DSH address | `https://dsh.example.internal/proxy/alice-report/` | Saved mapping and listening app; no extra DNS or Ingress |
| Custom hostname | `https://alice-report.apps.example.internal/` | Mapping, approved gateway `DSH_APP_DOMAIN`, DNS, TLS and an Ingress to the authentication gateway |

The suggested notebook hostname label is `<username>-jupyter`. Dots/underscores in a username become hyphens; check for collisions. Users choose a name and local port, not arbitrary domains, cluster Services, certificates or other runtimes.

**Path URLs work without new DNS. Hostnames are opt-in; saving an app does not allocate DNS or create an Ingress.** A configured hostname is a candidate until published. The current main site uses explicit Ingress host rules. A DNS wildcard alone does not publish a new name.

The gateway checks hostname ownership and environment before forwarding. Unowned/unknown app names are refused. Ordinary apps can remain at their hostname if compatible with that Host/Origin. Jupyter hostname links redirect to the canonical notebook path. Do not publish a direct unauthenticated worker Ingress.

## Check name and Ingress availability

The browser checks the protected DSH application registry. It does not establish DNS or Kubernetes hostname ownership. The operator separately checks all visible Ingress rules:

```sh
python scripts/plan_app_ingress.py \
  --user alice --name alice-report --domain apps.example.internal \
  --namespace llm --service dsh-environment-gateway \
  --tls-secret dsh-apps-tls --output /private/alice-report-ingress.yaml
```

Omit `--name` to suggest `alice-jupyter`. The command reads all namespaces, refuses exact-host or matching single-label wildcard conflicts and checks the deterministic Ingress resource name. Missing read permission is a failure, not proof of availability. `--inventory /private/ingresses.json` accepts an operator export; verify its freshness.

DNS resolution is reported separately. Wildcard DNS may resolve an unused name without reserving it or establishing certificate coverage. The command renders a candidate only. Availability is a point-in-time observation, not an atomic global reservation; recheck before applying and use one operator/controller as publisher.

## Operator hostname setup

1. Obtain an approved app-only DNS domain or explicitly allocated hostnames. Avoid a catch-all on a shared organizational domain.
2. Point the approved names/wildcard at the ingress controller. Use a trusted certificate whose SAN covers those names and a TLS Secret in the Ingress namespace.
3. Set `DSH_APP_DOMAIN=apps.example.internal` on the gateway. Keep `DSH_TRUSTED_HOST` fixed to the canonical DSH site. Ordinary user forms cannot change either setting.
4. Save the app mapping. Generate/review its exact-host candidate, then run:

```sh
kubectl apply --dry-run=server -f /private/alice-report-ingress.yaml
kubectl apply -f /private/alice-report-ingress.yaml
```

5. Alternatively, an approved delegated wildcard Ingress can route `*.apps.example.internal` to the same gateway. Kubernetes wildcards match one DNS label. DNS, certificate and Ingress wildcards are three separate settings.
6. Disable response buffering, support WebSockets, preserve original Host/Origin through the trusted ingress, deliberately set body/timeout limits and overwrite untrusted forwarded headers. Existing private-worker network policies continue to apply.
7. Verify normal TLS, anonymous and wrong-user denial, environment approval/revocation, assets, uploads, redirects, terminal/kernel WebSockets and persistence.

The gateway has no Kubernetes management token. Fully automatic exact-host registration requires a separate narrowly scoped operator controller; it is not implemented by allowing users/prompts to edit Ingress objects. Until that controller or a delegated wildcard domain is qualified, use the working custom path. Revert only routing/configuration on regression; never overwrite newer account, workspace or history content.

References: [Kubernetes Ingress wildcards](https://kubernetes.io/docs/concepts/services-networking/ingress/#hostname-wildcards), [Jupyter base URLs](https://jupyter-server.readthedocs.io/en/latest/operators/public-server.html#running-the-notebook-with-a-customized-url-prefix).
