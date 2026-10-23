# Verified login, terminal and Jupyter results — 23 October 2026

## Scope and actual results

The check began at 09:12 Bangkok time. Existing approved accounts were used;
credentials were not changed. These were authenticated HTTPS and WebSocket
tests, not a visual browser-layout review or a test of every registered account.

| Site / workspace | Normal login and identity | Terminal command | Jupyter calculation | Logout revocation |
| --- | --- | --- | --- | --- |
| Main DSH — Internet | Passed | Passed | Passed | Passed |
| Main DSH — No Internet | Passed | Passed | Passed | Passed |
| DSH2 — assigned owner Internet workspace | Passed | Passed | Passed | Passed |
| DSH3 — assigned owner Internet workspace | Passed | Passed | Passed | Passed |

Terminal checks opened real WebSocket sessions and confirmed the non-root user
ID and expected workspace hostname from command output. Jupyter checks read
actual Lab content and kernel specifications, created one temporary Python kernel
per workspace, and verified `6 * 7 = 42`, an OK execution reply and return to idle
over the kernel WebSocket. Only the temporary test kernels were removed.
Each test session was logged out; its saved authentication cookie was rejected.

## Preservation and limits

- No pre-existing kernels were listed in these four tested workspaces. This run
  therefore verifies temporary-kernel execution and cleanup, not continuity of an
  already running user kernel. The earlier on-demand rollout separately qualified
  held kernel connections. No server was stopped to force a live cold start.
- Original workspace Pods and existing server processes were retained. No
  workspace or supervisor restart, password change or local laptop window was used.
- Before/after inventories showed no added or removed workspace/state files and
  no notebook changes. The only changed files were IPython `history.sqlite`
  databases (also visible through legacy mount aliases). Test command-history
  storage was disabled; database hashes nevertheless changed during test sessions.
  This is not a claim that those databases were byte-identical.
- Password-store hashes were unchanged. Main's previous environment preference
  was restored. No notebook documents were created or saved.
- The No Internet row confirms the authenticated selected environment and its
  terminal/Jupyter operation; this run did not repeat outbound-network isolation
  probes. The earlier network-isolation qualification remains separate evidence.

## Code, documentation and repository alignment

The accepted on-demand Jupyter modules match the running gateways and the shared
source in both repositories. The private repository records deployment-specific
source; the public repository is a portable reference, not an infrastructure mirror.
Its configurable Gradio adapter intentionally differs from the privately pinned
site adapter. Deployment-specific manifests and vendored support modules are not
all exported as standalone public files.

A newer capacity-planner hardening change exists in both repository main branches
but is not included in the currently accepted Main gateway source. Repository
synchronization does not mean every newer change has been deployed. This edition
updates documentation only; it does not promote that candidate or change runtime
code. Cold-start qualification and earlier browser-layout checks remain separate
from this fresh authenticated functional run.

[On-demand Jupyter guide](JUPYTER_ON_DEMAND.md).
