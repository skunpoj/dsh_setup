# DSH site compatibility and maintenance — 24 October 2026

## Running application

The inspected Main No Internet and Internet workers, DSH2 and DSH3 contain DSH **0.2.1-rc.2**, with the same application image and matching inspected package metadata. Their installed managed inference transport and app supervisor have matching hashes. Authentication gateways and site guidance retain their required site-specific behavior.

The official npm channel marks **0.2.1-rc.2** as latest and **0.2.1-rc.3** as next. A preview announcement is not an instruction to change a running user's process. New releases require source-contract, image and copied-state qualification.

## Functional verification

- Normal authenticated owner login passed on all three sites, with identity and environment read back over verified TLS. Main local accounts require the Local DSH account provider; the page defaults to AD / LDAP.
- One separate synthetic conversation per site returned the exact expected nine-token reply through litellm-cluster/deepseek-v4.1-flash with zero retries. The request headers retained an 8,192-token output ceiling. These ordinary requests do not repeat a near-1M stress test.
- Main admin initially had a saved official-provider default and its test turn failed with 403. Supported native model selection corrected that owner's default to LiteLLM, and the subsequent reply passed. Existing conversations were not changed.
- The exact installed supervisor passed isolated startup, recovery after an owned child exited, generation restart, Stop, access revocation and file-marker checks on all three sites. Only fixture processes were replaced; fixture directories were removed.
- Existing owner-visible history IDs and admin-managed application definitions were compared before and after. Original histories were preserved; three clearly named synthetic acceptance conversations were retained as separate records. This is not a full byte audit of every user's history.

## Source and patch maintenance

The public setup build still pinned 0.2.0-rc.2 even though the private setup and running workers used 0.2.1-rc.2. The public source port uses the approved 0.2.1-rc.2 package and pi-ai 1.3.0 and includes the required client-tool build files. Public examples use generic addresses and portable dependency paths.

The compaction provenance guard had been added without updating its patch-target/export manifest. The repair records eleven reviewed upstream targets: eight protected files and three patched files. The complete patch was applied to integrity-verified official package sources and every resulting hash matched the recorded manifest. The coordinated guard-only add-on is active on all 34 workers through supported hot reload: 136 in-process checks, 51 source/component checks, six native compaction cases, and watcher add/remove/rollback checks passed. Existing services and compactor fibers were retained. The separate four-request model check did not establish independent actor recall, which remains inconclusive.

Qualification uses an isolated non-root, network-denied CPU workload with a read-only root filesystem, no service-account token, no GPU, no real workspace mounts and no credentials. Source/SDK/budget/patch/compaction/archive/workspace-tool checks and actual Jupyter HTTP/kernel checks are recorded separately from a new image build and runtime rollout. The catalog fixture was corrected to resolve its real guard dependency and perform the guard transformation in memory without changing the installed package. The final isolated rerun passed eighteen suites, including the new catalog check and the coordinated 51-check guard revision. Earlier failed sanitization fixtures are retained; the fixes use a portable Playwright dependency and preserve the malformed-URL rejection test without embedding a credential-shaped literal.

## Operating rules

Keep the shared core and upstream patches under one reviewed version contract. Keep account ownership, routes, credentials, environment access and storage assignments site-specific. Never copy account stores or user directories to make sites look identical.

An image upgrade replaces a process and cannot preserve its in-memory agents or kernels. Deploy to new or idle workers after acceptance, retain existing mounts and rollback images, and use only a proven supported hot-reload path for a running worker. A source commit or successful image build is not evidence that all active workers loaded a new patch.
