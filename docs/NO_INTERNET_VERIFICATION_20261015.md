# No-Internet label and runtime verification

Verification date: 15 October 2026, approximately 16:00 ICT.

## Actual network tests

Tests ran inside the existing Production containers, not an isolated canary. The Secure requests explicitly disabled curl proxy use. No HTTP(S)/ALL proxy variable was found in that container (the names containing `AUTH_PROXY` were Kubernetes Service port variables).

| Runtime | Destination | Actual result |
|---|---|---|
| `dsh-secure` | `https://github.com` | HTTP 000, curl exit 28, connection timeout |
| `dsh-secure` | `https://pypi.org` | HTTP 000, curl exit 28, connection timeout |
| `dsh-secure` | `https://registry.npmjs.org` | HTTP 000, curl exit 28, connection timeout |
| `dsh-secure` | `https://1.1.1.1` | HTTP 000, curl exit 28, connection timeout |
| `dsh-secure` | internal LiteLLM `/health/liveliness` | Response body `"I'm alive!"` |
| `dsh-internet` | GitHub, PyPI, npm | HTTP 200 for each |
| `dsh-user2` (DSH2) | GitHub | HTTP 200 |
| `dsh3` | GitHub | HTTP 200 |

Live policy readback selects `dsh-secure` through `dsh.bot.or.th/egress-mode=offline`. Its only egress allow rules select cluster DNS and namespace `llm` pods labelled `app=litellm`, TCP 4000. The current DSH2 and DSH3 pods lack this label and are not restricted by that policy. The DSH public host routes to the environment gateway; DSH2/DSH3 public hosts route to their separate legacy services.

These observations establish denial for the tested public endpoints from the actual Secure runtime, with internal inference connectivity retained. They do not reconstruct the user's earlier chat/session or establish which environment or remote execution tool that chat used. They do not establish an air gap or eliminate indirect leakage through allowed infrastructure, browser responses, or manual data transfers.

## Label correction

Before correction, the live gateway login HTML still said `Secure / Internal (Default)` with the off radio checked. The corrected source says `No Internet / Internal (Default)` and explains that only approved internal services are allowed and the Internet environment has separate project files/history. Internal identifiers `secure` and `off` remain unchanged.

Local tests verified the corrected login content, off-default behavior, environment routing and isolated-routing compatibility. Azure build 62680 builds the corrected gateway from GPU_server source commit `6f83e0c886fea16030c42a9cb1ceb1427e33d02e`. Deployment and image/content readback must be recorded after completion; source changes or build status alone are not proof of the live label.

### Completed rollout and readback

Azure build 62680 succeeded and read back registry digest `sha256:53c9f8222d48084175bb8e18abcfb8b953eea646539880bd3643b639572f1129`. Only `dsh-environment-gateway` was updated to this digest. Pod `dsh-environment-gateway-7c989d9689-pj4v7` reported that exact ImageID, Ready true and zero restarts after rollout. The Secure/Internet execution pools and GPU model were not restarted.

The public URL `https://dsh.aiportal.bot.or.th/login` returned HTTP 200. Its actual HTML contained `No Internet / Internal (Default)`, omitted `Secure / Internal (Default)`, and had the `value="off"` radio checked. The same checks passed inside the running gateway. A post-rollout request from Secure to GitHub again timed out with HTTP 000 while internal LiteLLM returned `"I'm alive!"`.

This verifies the deployed label and off-default login form plus the stated outbound tests. It does not identify the backend used by the user's earlier conversation; correlating that historical session is still required to explain its reported Internet access.

Gateway rollback manifest: `C:\Users\skunpojt\rollback-dsh-label-20261015\gateway.yaml`. Replacing the gateway invalidates its in-memory login sessions; it does not require restarting either execution pool or the GPU model.
