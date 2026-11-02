# OpenShell broker implementation status

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
