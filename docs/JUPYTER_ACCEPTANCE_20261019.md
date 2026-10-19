# JupyterLab qualification and rollout — 19 October 2026

JupyterLab 4.6.4, Jupyter Server 2.21.1 and ipykernel 7.4.0 were added to the DSH runtime image. They are installed during the build and start on demand inside the existing private execution environment. This change does not load another GPU model.

## Image and affected code

- Image digest: `sha256:4e07fd6fb377e1a5bb213bf97cb3ddb54275d28b8182a24cf5460425c4ff551c`.
- Image build: 62969; source commit `32c338012be1b3f1a72d5a451fb7ec5e9d656eae` in the infrastructure repository. The public implementation at build time was `da31366`.
- The launcher restores the gateway-stripped URL prefix at the Jupyter routing boundary. It requires the authenticated gateway identity and trusted browser origin; XSRF protection remains enabled.
- Gateway source SHA-256 for notebook API session-expiry handling: `5a74fe7865d6ccd5a05ecd18da23bbdc90059d8ed0ca79b330fd8a1569b63319`. This is a separately mounted overlay, qualified against the built image. Operator scripts and documentation were refined after the image build; they do not imply a different built image.

## Actual acceptance

| Check | Observed result |
|---|---|
| Linux image integration | Non-root server; Lab HTML; save/read notebook; real Python kernel WebSocket returned `42` |
| Server authentication checks | Missing identity, missing XSRF and hostile Origin were rejected |
| Authenticated gateway cases | Two synthetic users × No Internet/Internet: four notebooks and real Python-kernel executions passed |
| Anonymous forged identity | Notebook API returned JSON 401, with no identity-header bypass |
| Cross-user file requests | Four denials |
| Cross-environment file requests | Four denials |
| Test-worker replacement | All four saved notebooks retained identical content hashes; fresh kernels executed after replacement |
| Real browser interaction | Lab opened; Python kernel selected; cell changed to `print("browser-kernel-verified", 6 * 7)`; execution and persisted output `browser-kernel-verified 42` verified |
| Gateway registration regression | Two disposable accounts, default Internet denial, admin grant/revoke, four private histories, terminal writes/readbacks and restart persistence passed on matching candidate source |
| Main worker rollout | 28 workers: installed image digest/version read back, native history IDs preserved, 189 existing session files byte-identical, 56 workspace/state markers survived replacement |
| Additional owner instances | Two worker images updated; eight and one native history IDs retained, four durable markers survived; authentication/audit sidecars retained their previous images |

The additional-instance history checks established retained IDs and durable marker readback, not a before/after hash comparison of every legacy conversation file. Their history root differs from the main runtime; the operator helper now reads the configured `DSH_HOME`.

Private Deployment snapshots retain the former image and configuration for rollback. Mounts and storage contents were preserved. Rollback restores configuration and never overwrites newer notebooks or conversations with older copies.

## Operator lessons

The isolated candidate gateway initially lacked access to the restricted DNS resolver. A narrowly scoped candidate policy fixed the timeout; Production network policies were not opened. This was a candidate connectivity issue, not an inference failure.

The additional owner instances run their native DSH API on port 3081 behind a port-3080 authentication process. The first pre-update check used the main runtime's native port and refused before changing either instance. A bounded follow-up used their actual native port.

Browser automation must scope the kernel-selection buttons to Jupyter's dialog. A fresh kernel starts its execution counter at one even when the saved notebook already displays a previous execution count. Acceptance therefore checks a distinct newly generated output and its saved notebook content, rather than assuming the next counter is two. Synthetic notebook tests and temporary account credentials are separate from users' actual content.

## Usage and scope

Run `jupyter lab` from the selected DSH terminal, then open `/proxy/8888/lab` on that same site. Stop unused kernels. Notebooks retain the existing environment's storage, identity, quotas and network permissions. Logout ends gateway access but is not a promise to cancel detached kernels. No new 1M inference or throughput claim is made by these notebook tests.

See the [JupyterLab user guide](JUPYTERLAB.html).
