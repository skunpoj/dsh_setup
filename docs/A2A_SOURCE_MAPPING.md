# Managed A2A and SDK portable-source mapping

This page maps the portable A2A, DSH Python SDK, Claude Code and Deep Agents
source to a private site-release tree without publishing site configuration or
operational evidence. It does not claim that an image was built, deployed or
accepted live.

## Deterministic path rule

For the reviewed source set, remove this private deployment prefix:

```text
deployment/vllm/dsh-environments/
```

The remaining path is the canonical public path. Examples:

| Private site-release path | Public portable path |
|---|---|
| `deployment/vllm/dsh-environments/container/dsh-task-broker.py` | `container/dsh-task-broker.py` |
| `deployment/vllm/dsh-environments/scripts/a2a_worker_controller.py` | `scripts/a2a_worker_controller.py` |
| `deployment/vllm/dsh-environments/scripts/official_sdk_task.py` | `scripts/official_sdk_task.py` |
| `deployment/vllm/dsh-environments/tests/test_task_broker.py` | `tests/test_task_broker.py` |

The reviewed set contains 105 mapped paths. Every path follows this rule; no
path is redirected to another project or repository.

## Public sanitizations

Portable source differs only where a public example must not encode a private
site value:

1. The disposable SDK builder uses `/work/dsh-build-home` instead of a path
   that resembles a personal home directory.
2. A deployment-observer fixture uses
   `registry.example.internal/dsh-runtime` instead of a site registry.
3. The public release checker permits the exact deliberately invalid
   credential-URL fixture only at `gpu-stack/tests/test_portable.py`; the same
   value remains rejected everywhere else.

These changes do not alter the runtime protocol, task lifecycle, correlation,
guard, cancellation, recovery or ledger contracts.

## Verification boundary

The portable candidate is checked by:

- 227 A2A tests, with one platform-specific process-group test skipped on
  Windows;
- 198 official-SDK tests;
- 23 unattended-model-guard tests;
- 11 unattended-launcher tests;
- 40 task-broker tests;
- 19 managed Deep Agents policy tests;
- six public-release-gate tests;
- the public disclosure scan and public release checker.

Passing these source checks does not prove immutable image provenance or live
operation. A site release must separately bind the exact private source, public
portable source, dependency wheels, image digest, Test identity and rollback
receipt. SDK, Claude Code and Deep Agents must then pass the bounded live A2A
acceptance cases. Site hostnames, namespaces, registry destinations, identities,
credentials, build receipts, task results and private rollback evidence remain
in the private release system.
