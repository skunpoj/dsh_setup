# Capacity planner finite-number guard — accepted 23 October 2026

The executing capacity controller now rejects NaN, positive/negative infinity,
booleans and unknown or negative resource headroom. A rejected reading returns a
wait decision and never requests deletion of existing slots. Valid finite inputs
retain the previous bounded provisioning behavior.

Qualification reproduced the regression in the old planner. The corrected source
passed nine planner tests on Linux and three isolated Linux recovery tests.
After deployment, all nine planner tests also passed against the actual mounted
module. These synthetic cases did not request real account or workspace creation.

Only the separate capacity controller's immutable source reference changed. Its
other eleven bundled modules and base application image remained unchanged. The
fresh actual controller cycle reported a satisfied spare target, two ready spare
pairs, no pending slots and an empty deletion list. Policy, inventory and published
routes were unchanged. A guarded reverse-source patch and the original source
ConfigMap were retained for rollback; rollback was prepared, not exercised live.

All 33 original workspace Pods, specifications, restart counts, original server
and kernel processes, and checked history/notebook/settings hashes were retained.
Fresh ordinary-account login, terminal WebSocket commands, Jupyter calculation
and logout passed for Main in both environments and for each legacy owner site.
Only owned temporary test kernels were removed; no existing user kernel was
stopped. No password changes or local laptop windows were used.

## Repository and runtime boundaries

The executing planner bytes match the corrected shared source in both repository
main branches. Private accepted deployment evidence remains in the private
repository; the public receipt is a portable summary. Main and the legacy sites
have different roles, owners and protected deployment settings; alignment does
not mean identical deployments or publication of private infrastructure.

Gateway source bundles still contain an older **unused** planner copy. The login
gateway does not execute that module: the separate capacity controller does.
Restarting gateways simply to replace that unused copy would risk active notebook
connections and is unnecessary for the effective fix. This acceptance does not
claim every bundled file or every newer unrelated repository change is deployed.

The independently coordinated Jupyter Start-idempotence release has its own
acceptance evidence; it is not part of this controller-only change.

[Interactive verification](JUPYTER_INTERACTIVE_VERIFICATION_20261023.html).
