# Acceptance checklist

Record results privately for your deployment; do not copy infrastructure
inventory or credentials into this public repository.

1. **Source/build:** reviewed image and model digests, pinned package contracts,
   successful container build, no embedded credentials, rendered schema accepted
   by the intended cluster. Source/schema checks are not runtime acceptance.
2. **Authentication:** correct login, wrong-password denial, no self-registration,
   password-change persistence, logout revocation, ordinary-user admin denial.
3. **Isolation:** two synthetic accounts in both environments; peer history,
   attachment, report and direct-port access denied. Terminal returns non-root
   UID; no account-store mount, API token, host socket or unrelated volumes.
4. **Workspace:** first-use registration, real create/write/read/delete marker,
   correct private path and persisted session registry. Replace a synthetic pod;
   confirm original file bytes/history survive and peer files remain inaccessible.
5. **Network:** public-domain and direct-IP probes fail in No Internet; required
   inference works. Internet can fetch a public dependency but cannot reach peer
   runtime/data/backend ports. Model direct access from workers is denied.
6. **Inference:** short exact response, streaming, tools, two/four ordinary
   requests, exact overflow rejection and client-override rejection. Validate
   actual token usage and output, not just HTTP status or pod readiness.
7. **1M:** use progressive synthetic testing from the context guide, including
   mixed short/long traffic, cancellation, compaction and recovery. Do not repeat
   disruptive stress on a shared service without an agreed operating window.
8. **Operations:** image/profile rollback, Secret/database/user-state restore,
   audit capacity/retention, resource limits and removal of temporary identities.

Do not mark every boundary closed from one successful credential, a Ready flag,
an empty filtered screen or a saved test report. Recheck affected behavior after
changes, and state what remains unverified.
