# Gateway source cleanup — accepted 23 October 2026

The unused capacity planner has been removed from Main DSH's active gateway
source mount. The other 26 modules, including authentication and on-demand
Jupyter code, are byte-identical. DSH2 and DSH3's canonical gateway source
bundles already had no planner copy and were unchanged. The fixed planner
remains in the separate executing capacity controller.

The gateway source is immutable, so removal required replacing Main's gateway.
An active admin-workspace connection initially caused the cutover guard to stop.
The operator then explicitly authorized forcing that gateway connection to
disconnect. A fresh pre-cutover check still required zero running kernels.
This was not a claim of uninterrupted browser connections during replacement.

All 33 original workspace Pods, specifications, restart counts and original
server processes were retained. Checked native histories, notebook files and
Jupyter settings hashes were unchanged. Password/account stores, settings,
application policy, routes and existing browser sessions were preserved.
No user workspace, Jupyter server, supervisor or capacity controller was
restarted. No password changes or local laptop windows were used.

The candidate without the planner passed eight actual gateway regression tests.
Gateway packaging/projection suites passed seven tests in each repository.
Future private shared-controller deployments now exclude the planner from
gateway file projections while retaining it in controller sources.

Original immutable source ConfigMaps and versioned evidence are retained for
rollback. Removal applies to active gateway source mounts, not historical
archives or the planner required by the real capacity controller. The base
runtime image was not rebuilt. Newer unrelated image/build changes require
their own qualification and rollout and are not silently included here.

[Capacity planner acceptance](CAPACITY_PLANNER_ACCEPTANCE_20261023.md).
