# OpenShell broker implementation status

## Independent source successor: isolated official SDK control

The explicit SDK broker bootstrap is Test-only and off by default. A finite
root-protected server descriptor must bind the exact controller, peer, session,
package-admission and scope source hashes, admitted package hash, expected image
digest and source commit. Revocation, replacement or expiry disables subsequent
admission. Every bound source is directly re-read and rehashed at each admission.
An independently supplied protected deployment observer must match the actual
Test Pod, workload and namespace UIDs and classification; a qualification flag
and descriptor alone cannot enable the service. No observer is provided by the
default server entry, so it stays unavailable until that protected integration
exists. Production identity is refused even with the Test flag set.
Existing owner-bound records are reconciled without creating a new
task or retrying a model. Production configuration is deliberately refused by
this loader; it cannot turn source qualification into operational acceptance.
The actual isolated scope factory, matching wheel admission and physical
source/image observations still must be supplied and independently qualified.

The candidate `official_sdk_deployment_observer.py` verifies a disposable Test
Job against named API object snapshots: namespace/Pod/Job UIDs, owner reference,
Test-purpose labels, exact specified/running image and stable resource versions.
The namespace itself must also carry platform-owned Test/qualification labels;
Job/Pod labels cannot reclassify an existing shared or Production namespace.
The verifier never relabels any actual namespace. Running image IDs are parsed
as exact admitted CRI forms and compared by their complete SHA-256 component.
It requires a separate protected identity of the *executing broker*, preventing
observation of another Test Pod from admitting a Production broker. The finite
Job is one completion/one parallel worker, no retries, restart Never and at most
300 seconds. Named GET, independently attested local identity and physical
isolation remain injected protected dependencies, with no default credential,
environment or network route. This verifier is not wired or live-qualified by
its synthetic tests; no actual Test resources are created.

`official_sdk_test_api.py` now supplies the fixed Namespace/Job/Pod named-GET
adapter and a concrete one-shot HTTPS/mTLS requester for the protected control
plane. Only its three exact resource paths and the in-cluster Kubernetes host
are permitted. The requester explicitly verifies CA/hostname, uses fixed
root-protected client identity mounts and refuses encrypted-key password prompts.
There is no kubeconfig/token discovery, Windows authentication, proxy, redirect,
retry, list, exec or mutation interface. SDK workers must never receive these
identity mounts. Source tests replace all certificate loading and networking;
issued certificates, actual scoped RBAC and live TLS verification remain required.
Default broker activation stays off. Observer and API source hashes are included
in every bootstrap admission recheck.

`official_sdk_release_admission.py` verifies the separately trusted builder
receipt and exact SDK/runtime wheel pair before image admission: upstream pin,
version/dependency, wheel tags, sizes/hashes, bounded archive paths, complete
RECORD integrity and exact x86_64 ELF runtime payload. Its result is VERIFIED,
not a signature or Production acceptance. Actual wheels and builder/image
provenance still have to be produced through the approved publisher. The safety
ceilings do not establish compatibility with an artifact that does not exist yet.

The official SDK session candidate no longer imports or constructs the SDK in
the broker process. Its default is an authenticated, sequential private-pipe
proxy to a protected supervisor's isolated child. The child starts with `-I -S`,
clears inherited environment values before SDK import and admits the exact
retained SDK wheel, installed RECORD and source bytes. Cached Python bytecode
is not used for SDK imports. Version labels alone cannot admit a package.

Every capability/admission read rechecks protected package content and a fresh,
short-lived supervisor admission bound to the owner, generation and package
hash. That admission must attest isolated control and no broker credential
mounts. Missing/revoked evidence leaves the SDK unavailable. The supervisor
must implement the actual isolated transport; there is no local-process fallback.

This is SOURCE ONLY. The frozen reviewed revisions remain unchanged. No package
pair, protected admission, immutable image, deployment or live runtime acceptance
is supplied by these source changes. Native SDK handoff and OpenShell qualification
remain incomplete. The three internal real-provider starts previously accepted
must not be repeated; the total five-start allowance is exhausted.

The reviewed native boundary now lives in this same source tree at
`scripts/openshell-native/`: gateway identity binding, complete-worker handler
and cancellation controller. Its eight source tests verify the ordered journal,
broker, transport and supervisor cancellation contract. The handler remains
disabled and its protected dependency transport is not yet connected. These
source passes do not satisfy any real-image OpenShell acceptance gate.

`scripts/openshell_task_binding.py` provides typed bind, resolve, dispatch,
revoke/fence and exact stop operations over the existing broker Task journal.
The task persists `openshell` metadata in its existing `task.json`; no second
journal is created. Dispatch reserves its operation before transport and refuses
automatic replay after uncertain completion. Stop verifies the exact worker UID
before recording completion; a changed stop operation is refused.

This module is a source candidate. Typed broker POST routes now exist at
`/v1/tasks/<id>/openshell/{bind,resolve,dispatch,revoke,stop}` behind the existing
broker bearer authentication. They remain disabled unless an admitted service
is explicitly injected by the server. The service requires the assigned subject
and generation from server configuration and rejects binding/identity fields in
the request body; the body is exactly `{"approved":true}`. A qualified transport
must supply native worker allocation and read-only allocation lookup, native dispatch, exact stop
and exact absence receipts. The authenticated gateway must resolve the assigned
workspace broker and its subject/generation without accepting these identities
from browser request fields. No generic Kubernetes or secret retrieval interface
is part of this implementation.

Worker creation now reserves its allocation operation in the existing Task journal
before contacting the transport. The transport returns the actual native worker
UID with exact owner/task/generation/binding and operation fields. If creation
times out or returns an invalid receipt, the task remains fenced in
`allocation-reserved`; another bind or dispatch cannot create a duplicate.
`resolve` can recover that same allocation through read-only lookup. Expired
recovered identities stay fenced and remain available for exact cleanup.

Remaining integration: gateway-to-service wiring using protected server identity,
production transport, immutable image lock and registry provenance, disposable mTLS and
mock-provider manifests, expiry enforcement in the worker, and all 25 real-image
Test gates including crash/recovery, descendants, fencing, cleanup and rollback.
The UI must continue to show OpenShell unavailable until those gates pass.

## Broker task lifecycle

The task-create endpoint now accepts the OpenShell backend only when the server
has an explicitly injected qualified service and the authenticated subject
matches its assigned owner. The registry starts `service.run_task`, without
constructing a local runtime process. Native output and typed exit events enter
the existing Task event stream. An exit is held in `finalizing` until exact
native stop and absence receipts pass; uncertain cleanup is `interrupted`, not
completed. Interrupted native workers with unresolved binding state block new
task admission. Native handoff now uses a separate binding, actual worker UID,
operation and correlation ID for each of two stages. The first worker must pass
exact stop and absence verification before the second allocation. Cancellation
between stages, a failed first stage or uncertain absence prevents the next
stage. This is source-tested with an injected synthetic transport; it is not
live OpenShell acceptance and never falls back to a private-workspace process.

Cancellation calls the native revoke/stop/absence path. `recover_pending`
reconciles existing journal bindings from an old generation, fences and stops
them, and records absence without dispatching a model or allocating a replacement.
Allocation uncertainty is resolved only by lookup. These paths have integration
tests through the broker HTTP server using a synthetic native transport. They
are not installed-source, real-image or live native runtime acceptance.

## Worker execution and native identity limits

`scripts/openshell_worker_execution.py` now supplies a bounded worker execution
function. It compares the full envelope against supervisor-assigned identity,
requires the identical expiry, reserves one execution per binding with exclusive
file creation and fsync, and retains the reservation after launch failure. An
expiry watchdog terminates the process group; exit cleanup also fences tool
descendants. Prompt text is excluded from the reservation. This function still
requires protected assignment and native transport wiring; it is not an
activated worker entry point and its tests do not prove kernel containment.

The successor source now includes `container/dsh-openshell-worker.py`, installed
by the Dockerfile, and `scripts/openshell_worker_entry.py`. It reads a bounded
stdin envelope and a fixed root-owned, non-user-writable assignment, then calls
the execution reservation/watchdog. Broker and worker share
`scripts/agent_runtime_commands.py`; every supported runtime invokes the same
guarded launcher with one allowed model start. This image has not been built or
deployed, and the assignment injection is not connected to a native supervisor.

`scripts/openshell_native_rpc.py` uses the pinned generated request types for
CreateSandbox, read-only GetSandbox and streaming ExecSandbox. It carries the
existing durable operation ID into native `request_id`, confines names to the
binding and an assigned workspace, sends the envelope on stdin to the fixed
worker executable, and sets a finite execution timeout. The reviewed SDK's
convenience methods omit `request_id`; the adapter does not rely on them.
No RPC was sent in its tests. Name-only StopSandbox remains explicitly refused
until the supervisor supplies exact identity fencing and absence verification.

Pinned gateway compatibility now constrains workspace and sandbox names to
19 characters. The binding-derived sandbox name is shortened; allocation and
read-only lookup additionally require the exact full binding label, workspace,
name and a nonempty native sandbox ID. A collision or foreign receipt fails
without creating a replacement or retrying. Nine focused RPC tests pass; these
are generated-request boundary tests, not real protobuf/image acceptance.

## Journal-to-native transport

`scripts/openshell_broker_transport.py` now connects the existing Task state to
the native RPC boundary. It verifies durable allocation/dispatch reservations,
matches native labels to the allocation operation, obtains and persists an exact
Pod UID through protected read-only supervisor observation, and supplies the
stage's in-memory prompt/runtime/correlation to the fixed worker entry point.
Unknown assignment, a replacement Pod or an uncertain dispatch never causes a
second native launch. Stream output and exit events return through the broker.

Supervisor stop and absence receipts must match the full owner/generation/task/
binding/native-worker/Pod identity and operation. This also covers cancellation
after allocation but before dispatch. These methods remain injected protected
dependencies; their actual installed implementation is still required.

Each native stage uses its reserved operation ID as the guarded launcher's
execution ID. `DSH_PARENT_TASK_ID` retains the parent task link, and persisted
stage metadata includes the execution ID. This permits the intended second
stage without reusing the first stage's one-start allowance. The binding
reservation still permits only one execution per worker binding.

The latest transport/RPC/worker run passed 25 Python source tests, including a
two-stage broker-to-transport lifecycle. This count is unrelated to the 25
product gates, which remain unexecuted against real native images.

## Protected startup and current SDK wiring

`scripts/openshell_bootstrap.py` is now called by broker startup. No descriptor
means disabled. A root-protected, hash-bound factory can admit a finite Test
window. Production configuration additionally requires all five image pins,
matching source/policy/transport identity, 25 distinct gate-evidence files and
rollback evidence whose bytes match the accepted receipt. Startup recovery
fences/stops recorded workers without allocating or replaying. Admission expiry
blocks new binding/dispatch while permitting exact cleanup. The 43 focused
bootstrap/service/broker source tests pass; no accepted Production receipt exists.

Live corrected-broker preflight confirmed official SDK and runtime 0.2.1rc2 in
`/opt/dsh/deepagents`, but `/usr/local/bin/dsh-sdk-task` still imports the custom
`dsh_deepagents_sdk.create_dsh_agent`. Thus installed official packages do not
prove that Web DSH's `sdk` choice executes the official SDK. The approved
three-start Test was stopped before submitting any model task; its permission
fix and source hashes passed, and exact resources were removed. Official
launcher wiring and its new frozen packet must be qualified before those calls.

The Test-only official adapter now imports `deepseek_harness.DeepSeekHarness`
directly, requires both exact 0.2.1rc2 distributions, reserves an exclusive task
home before startup, and accepts only the local guarded endpoint. It uses the
full SDK profile with read-only execution, session upload disabled and the retry
plugin disabled. Five focused source tests pass, including duplicate and failed
start replay refusal. These tests use a fake Harness factory, not model calls.
The candidate is not installed and does not replace the resumable launcher.

A fresh read of the installed SDK confirms that its `initialize()` and config
do not expose the newer upstream `approval_requests` argument. The latest online
SDK examples therefore cannot be used verbatim for this pinned wheel. Native
approval/resume integration needs that version's actual protocol; neither the
read-only qualification nor a successful model answer would prove it complete.

The V3 disposable Test subsequently initialized the actual full SDK profile and
returned the exact synthetic marker through the Test gateway/broker. Its guard
reserved and completed exactly one upstream request with HTTP 200. Acceptance
remains incomplete: neither root nor nested SpendLogs metadata retained that
operation's DSH correlation ID. A matching-time log is not an identity join.
Claude and Deep Agents were held. The exact Test Pod and ConfigMap were removed,
and both absences were read back. One approved model start has been consumed.

The successor guard derives `x-litellm-call-id` from its durable operation UUID,
rejects caller-supplied IDs in headers/body/metadata, and records a typed response
ID plus whether the server confirmed the expected value. The running LiteLLM
implementation explicitly accepts that request header and returns it. Nineteen
focused guard/official-adapter tests pass using mock transport, including
forgery refusal, server echo binding, missing/malformed identity handling,
duplicate suppression and concurrent requests. This successor is not deployed;
V4 requires additional model authorization before any new submission.

## Actual Linux signal-mechanism check

The entry point now converts SIGTERM/SIGINT into a cancellation flag. The worker
checks that flag before launch and during bounded waits, then executes process
group cleanup before returning. Thirteen focused worker/entry tests pass.

A disposable Linux Pod ran the same source bytes with a synthetic client and
grandchild, without invoking any model client. Both child processes were alive
before SIGTERM to the worker. The worker returned 143, both recorded descendant
PIDs were absent after reaping, and no emergency cleanup was needed. The Pod
completed; exact owned resources and namespace were removed, with absence read
back. This verifies that mechanism on Linux, not authenticated web cancellation,
native supervisor signal delivery, all descendants under OpenShell, or T16/T25.

The first attempt failed before client launch because the no-symlink assignment
reader rejected a projected ConfigMap key. A read-only `subPath` file bind for
`/run/dsh-openshell/assignment.json` corrected the mount without weakening that
reader. Source bytes were identical in both attempts; the assignment expiry was
renewed for the corrected finite run. Deployment templates must use a protected
regular-file bind, not a projected key symlink. Both attempt receipts are kept.

Pinned upstream review: `NVIDIA/OpenShell` commit
`bdb956f2cd65a635f1294fccf1d138d263bf650f`, `proto/openshell.proto` exposes durable
`request_id` for DeleteSandboxRequest, StopSandboxRequest and ExecSandboxRequest.
The stop/delete requests do not expose an atomic expected-worker-UID precondition.
The adapter must therefore prove exact native identity and replacement fencing
in Test, not infer it from a read-before-stop plus a name-based mutation.
`workerUID` in a native receipt must identify the actual OpenShell sandbox;
underlying Kubernetes Pod UID/absence needs its own supervisor receipt.

## Kubernetes identity and observation implementation

The isolated successor from local candidate `0a0a45b3` now adds
`openshell_kubernetes_identity.py` and `openshell_kubernetes_observer.py`.
They join the native Sandbox resource UID to workload and supervisor Pod owner
UIDs, bind the full task scope, pin image references and distinguish Pending
observation from actual running-image verification. Replaced resources,
foreign owners, selector injection, incomplete/unversioned/paginated API lists,
terminating Pods and automatic workload service-account token mounts refuse.
Only the existing Task journal persists verified identity; no credential or
alternative cluster route is discovered. Twenty-two focused source tests pass.

The verifier uses the pinned upstream `openshell.ai/sandbox-workspace` label.
Fixtures contain that literal upstream key rather than deriving all metadata
from the implementation constants. Supervisor owners may omit `controller`
but must never set it true, matching the pinned native source.

These modules are not connected to a deployed factory. Assignment publication,
atomic native dispatch/stop fencing, actual API transport, source/image build
and all 25 live gates remain incomplete. The public pinned Exec/Stop APIs do
not take an expected Pod UID. A read-then-name-based operation is insufficient.
The driver permits PVC caller volumes only; the prior ConfigMap file-bind CPU
test does not prove that the public native driver can provision that mount.
No PVC, admission webhook, IAM or Production mutation is authorized by this
source change. Docker source-test wiring includes the new modules; no image
build or deployment is claimed.

## Physical Pod identity at the worker boundary

The execution envelope and retained one-start reservation now include `podUID`.
The worker reads `/run/dsh-openshell/pod-uid` separately from its assignment,
requires a root-owned non-writable regular file, and rejects missing, invalid or
different identities before launching a client. A legacy envelope without the
Pod identity is rejected. Environment variables are not accepted as identity.

The admitted operator still must provision this file from actual Kubernetes
`metadata.uid`, together with the protected assignment. That mount is not yet
implemented in the pinned native driver. This fail-closed entry point does not
make the public name-based Exec API atomically identity-fenced, and does not
replace protected dispatch/stop implementation. All 86 OpenShell source tests
pass; this is source evidence only, with no model call or live gate claimed.

## Conditional native resource retirement

`openshell_kubernetes_api.py` now restricts the injected authenticated API to
Sandbox and Pod operations in the admitted namespace. Each DELETE carries both
UID and resourceVersion preconditions; it preserves ordinary grace/finalizers
and does not retry, force-delete or inspect Secrets. This follows Kubernetes
[DeleteOptions](https://kubernetes.io/docs/reference/kubernetes-api/definitions/delete-options-v1-meta/)
and [Preconditions](https://kubernetes.io/docs/reference/kubernetes-api/definitions/preconditions-v1-meta/).

`openshell_kubernetes_retirement.py` checks the existing stop reservation and
frozen resource identities, reserves each conditional deletion in the same Task
journal before the API request, and keeps uncertain operations reserved. A
replaced sibling refuses before any deletion. Direct GET absence and complete,
versioned native-ID lists must both pass. An uncertain deletion can be resolved
through readback without resubmission.

This component returns `resourcesAbsent`, never `stopped`, and explicitly marks
`processExitVerified=false`. The protected supervisor still must prove process
termination and integrate gateway/native bookkeeping; Kubernetes record absence
is insufficient on its own, particularly during a node partition. No public
name-only Stop call is substituted. Fourteen focused mocked API/retirement tests
and the full 100-test OpenShell source suite pass. No authenticated transport is
created here, and no cluster DELETE, model call or product gate was executed.

## Actual client transport qualification findings

The official SDK rc2 Test call returned its exact marker and its operation
joined the guard ledger, LiteLLM response header and one persisted SpendLogs
row. That bounded marker test does not establish SDK approval/resume, a
Production web-originated call, or agent delegation.

Actual Claude Code 2.1.301 exposed three pre-inference compatibility gaps:
machine policy did not pin the task guard, Windows-transferred executable
shebangs contained CRLF, and its `/v1/messages?beta=true` route did not match the
guard's exact path allowlist. A disposable Test-only read-only machine policy
now pins the bound loopback endpoint and uses a dummy local key helper. Source
supports an explicit loopback listen port and refuses port conflicts without
endpoint fallback. Transfer packets normalize and check LF executable bytes.
Only the observed Anthropic beta query form is accepted; other queries refuse.

The first forwarded Claude request then failed in LiteLLM's custom-OpenAI
adapter on the unsupported `safeguards` keyword. The guard now refuses this
capability locally before reading upstream credentials or reserving a request.
It does not strip a requested safeguard or claim to implement Anthropic's
classifier. The actual installed CLI's custom-endpoint negotiation was tested
against the corrected guard and a fake loopback provider: one mock forward,
correct mock result, zero real-provider requests. CLI cost estimates in that
mock result are not billing evidence. Live Claude acceptance remains open.

The Deep Agents launcher also dropped its guard/task/correlation environment.
It now preserves only the complete validated loopback tuple while continuing
to remove provider keys, external endpoint overrides, proxies and Python hooks.
Its live marker and ledger reconciliation remain contingent on Claude passing.

Validation: 24 guard/launcher tests and 19 managed-agent tests passed; the actual
CLI mock protocol passed. No Production rollout is implied. These corrections
still need immutable-image integration, correct root-owned task policy
selection, full lifecycle acceptance and the separately admitted OpenShell
qualification. A general workspace machine policy must not be changed silently
to a transient task endpoint; the Test fixture is explicitly disposable.

### Subsequent bounded client acceptance and native SDK approval gap

SDK, Claude Code and Deep Agents each subsequently passed one real internal
Test marker execution, with exact returned content and a single operation
joined across the guard ledger, server call UUID and persisted LiteLLM
SpendLogs. These later receipts supersede the pending marker statuses above.
The five-start authorization is fully consumed, including earlier failed
attempts. No additional real provider request is admitted by these results.
The disposable fixtures were archived and removed with UID checks; they were
source overlays on a retained image, not an immutable successor deployment.

A separate credential-free native SDK test used the installed matching
`0.2.1rc2` SDK/runtime pair, a loopback fake provider, a Pod-specific deny-egress
policy and a failed TCP positive-target connection check before SDK startup.
It requested `workspace-write`, taken from the runtime's actual tool schema,
while the session was read-only and `approvalRequests: true` was sent through
the generic initialize API. The real native tool result was:
`sandbox escalation to "workspace-write" requires approval, but no approval
channel is available`. No `approval/request` arrived, no probe file was
written, and both the Pod and its policy were UID-deleted with absence checks.

Thus merely sending an initialization flag does not supply the missing native
approval channel. Do not substitute the LangGraph checkpoint helper for the
official SDK, silently authorize writes, or represent an accepted marker as
approval/resume acceptance. The upstream SDK source with typed approval
support and its matching runtime must be built and admitted together, then
tested with explicit rejection, one-operation approval, cancellation and stale
decision fencing. No compatible native successor image has yet been built.
OpenShell remains **0/25 live product gates**; resource retirement, native
process-exit proof and full rollback remain separate requirements.

### Native SDK approval bridge source candidate

`scripts/official_sdk_approval.py` now supplies the broker side of the reviewed
`approval/request` protocol. A protected launcher must supply its native client,
authenticated subject, generation and session. The initial admitted candidate
had no launcher constructing this bridge; the independent session-runner source
below adds that path. Neither version enables approvals in the incompatible
installed rc2 runtime.

The bridge stores its binding and one pending decision in the existing Task's
`task.json`. It binds subject, generation, task, project, correlation, native
session and tool call; missing call IDs, stale identities, repeated tool calls,
unknown wire fields and repeated decisions refuse. Arbitrary native reason text
and tool arguments are not copied into the journal. A decision is persisted
before exactly one native response. A timed-out response remains uncertain and
cannot be replayed. The existing Task writer now flushes/fsyncs the temporary
file before replacement and fsyncs the directory on POSIX. Actual filesystem
crash durability still requires qualification on the deployed storage.

The existing authenticated approval route and page can carry a native decision
ticket and offer allow-once/reject. Allow-once is additionally restricted to a
task admitted for writes. The old checkpoint resume body cannot approve a
native operation. Native cancellation requires a protected stop callback with
exact identity/operation and independently verified process exit; absent or
uncertain evidence produces `interrupted`, never `cancelled`. Recovery fences
saved native request IDs and blocks new task admission until native cleanup is
verified. It never starts a replacement session or forwards an old approval.

Source checks use the actual Task journal and HTTP handler with a synthetic
native client, plus the generated page script with synthetic HTTP responses.
They establish these source contracts only. Matching native runtime packaging,
protected launcher/lifetime integration, stage-specific handoff, bounded native
transport cancellation and private real-image lifecycle acceptance remain
required before any operational claim. OpenShell still requires its separate
protected worker binding and all 25 live gates; this private-workspace bridge
explicitly refuses being substituted for that backend.

Independent review rejected the initial bridge candidate: terminal recovery
incorrectly fenced a previously verified stop, and native event reads lacked
the subject check already enforced on decisions. The corrected candidate saves
only the checked exit-receipt fields and retains `stopped` after recovery only
when that proof matches the terminal Task's exact identity and operation.
Missing or changed proof remains fenced. Authenticated native event reads now
check subject before reading events or returning any approval ticket. Regression
tests cover new-task admission after verified-stop recovery and refusal of
foreign/missing subjects without event or ticket disclosure. These corrections
remain source-only pending independent review and the runtime prerequisites.

The next re-review identified missing natural finalization and external calls
held under the journal lock. The successor adds a verified finalization path
for both normal and failed exits in `Task.run`; terminal state is recorded only
after the same exact native process-exit proof required by cancellation.
Cleanup uncertainty remains `interrupted` and blocks admission.

Decision and stop reservations are now persisted under the Task lock, while
external callbacks run outside it. Waiting is bounded to at most five seconds.
Timeout stops observation only: it does **not** kill the callback or establish
native process exit. Its operation remains reserved, no retry is allowed, and
new task admission stays blocked. Cancellation can fence/stop the same native
process while a response callback is blocked. A late response cannot reopen a
fenced or stopped task. A late stop receipt can be read from the same in-flight
call without invoking the stop again; after broker restart, protected read-only
native reconciliation is still required. A timeout is never a stop receipt.
Concurrent cancellation supersedes successful-finalization intent without a
second stop. Native process termination must still be supplied and qualified by
the protected launcher; daemon-thread observation is not a process sandbox.

## Independent official SDK session-runner successor

Following the human's decision to resume DSH source work independently, the
successor leaves admitted `ad78056d` and private `3d812c52` untouched in their
existing checkouts. `scripts/official_sdk_session.py` adds a session runner
using the official `DeepSeekHarness` API with native approval requests. It
requires a qualified protected runtime scope and the existing per-task model
guard. No SDK package, credential, supervisor or worker is discovered or created
as a fallback. The scope must supply no-spawn preflight, one fenced launch,
exact native identity and verified process/descendant stop receipts.

The runner reserves launch identity in the existing Task journal before start,
checks task/correlation/owner/generation, streams metadata-only progress, and
forwards actual native approval requests to the admitted one-shot bridge. It
captures a checked final response privately and finalizes only after native exit
proof. Unknown native request methods fail and retire the session. A late start
cannot override a fence. Recovery only inspects the old recorded session through
the protected scope: no SDK construction, model call, process start or old
approval replay. Live, foreign, incomplete or uncertain receipts stay fenced;
repeated observation uses the same lookup handle. An unverified stopped label
is not accepted as recovery proof.

`container/dsh-official-sdk-runtime.py` is the proposed Linux child entry. It
creates a session for that child only, uses a fixed checked image source path,
and requires a root-protected admission for the exact matching SDK/runtime
pair and source pin. It clears inherited environment values and execs only the
runtime whose actual bytes match both that admission SHA-256 and its wheel
RECORD. The child receives a loopback guard URL and dummy local key, never a
copied provider credential. No admission file is created by these changes. The
proposed `0.2.2a2` pair remains unbuilt and unadmitted; the installed `0.2.1rc2`
pair is explicitly refused by this new path. Existing base/managed image layers
and package pins still require their separately reviewed composition change.

The authenticated broker can dispatch SDK tasks only to an explicitly injected
qualified session runner; missing configuration returns unavailable instead of
silently running the older LangGraph helper. Owner binding is checked before
creation. Capability metadata lets the page disable the unavailable native SDK
and unqualified SDK handoff. A new SDK request cannot bypass that rule through
the OpenShell selector: its official-native worker path is explicitly refused
until the protected native worker adapter is qualified. Existing legacy checkpoint records remain readable
and retain their explicit approval continuation; they are not new native SDK
tasks. Other runtime and OpenShell routes retain their existing source contracts.

This is source-only work. Tests use the actual Task journal and loopback HTTP
handler with synthetic SDK and supervisor peers; the child-entry tests validate
parsing, environment allowlists and fake payload hashes without exec. No actual
SDK runtime, model provider, package installation, image build or cluster action
was used. A real protected supervisor/factory, admission/wheel artifacts,
bounded native process lifetime, deployed storage, SDK stage handoff and
current-image browser/runtime acceptance remain required. OpenShell remains
**0/25 live gates** and is not enabled by this session runner.

An immediate native result can race the sender's decision-journal update. The
runner therefore waits for the admitted bridge's bounded internal settlement
signal before consuming a result from a reserved decision. That signal is not a
model success or process-exit receipt. Cancellation and uncertain decisions
remain fenced. Managed SDK sessions block next-task admission until observer
cleanup finishes; an in-memory live session cannot be treated as a restarted
session by the read-only recovery method.

SDK-enabled server configuration must use a broker interpreter that can import
the admitted matching distributions. The existing managed Python 3.14 layer is
separate from a base-system Python environment; do not add one interpreter's
site-packages to another interpreter's path. Actual installed-wheel origin,
interpreter, runtime SHA and supervisor enforcement must be verified together.
No protected server factory or real supervisor implementation is supplied or
activated by this source increment; those remain the next qualification inputs.
