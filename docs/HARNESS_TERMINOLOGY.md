# MultiHarness terminology and architecture contract

This vocabulary aligns the current DSH library with [Addy Osmani, Agent Harness Engineering](https://addyosmani.com/blog/agent-harness-engineering/) (19 April 2026). It describes our architecture; the article is not evidence that a DSH feature is implemented or operational.

## Core vocabulary

| Term | Meaning in this library |
| --- | --- |
| Model | The learned inference capability. A model name does not identify an agent, harness, gateway or deployment. |
| Agent | A model operating through a harness to pursue a task. Name the task route, harness, model and execution context when describing a tested agent run. |
| Agent harness | The non-model system that supplies the execution loop, tools, context, state, constraints, observations and recovery behavior. |
| Harness engineering | Engineering those mechanisms around desired behavior, then using observed failures and repeatable checks to improve them. Adding a written instruction alone does not establish enforcement. |
| MultiHarness | The DSH platform integrating multiple agent routes with shared identity, routing, workspace, policy and operational services. Keep this product spelling. It is not a model or a single inference engine. |
| Governed integration | A route connected to DSH controls. State which controls are configured, source-tested, deployed or live-verified; the adjective does not establish universal protection. |
| Agent integration route | The comparable unit for the official native DSH Python SDK route, Claude Code route and Deep Agents route. These are different abstractions, not three interchangeable SDKs or three models. |
| DSH Python SDK | An SDK interface to its native agent/runtime facilities. An SDK import, local adapter, wrapper or mock is not evidence of the official native route. Retain the exact distribution, version and executed path in qualification evidence. |
| Claude Code | A coding-agent harness/product. Distinguish it from the Claude model and from an independently built SDK application. |
| Deep Agents | A harness framework used to construct an agent application; identify the configured application and model separately. |
| Runtime | The running process/session or execution environment. Qualify it: agent runtime, task worker, model-serving runtime or container runtime. Runtime is not a synonym for SDK. |

## Component roles and connections

DSH web is the user interface. `dsh-gateway` supplies authentication and user/environment routing. The task broker coordinates managed tasks and their ownership. These shared services support harness execution; the web page alone is not the harness.

Managed-task model requests pass through their task guard to `litellm-gateway`, then the same-pod `context-forwarder`, then the selected inference backend. Interactive clients have a separately configured direct LiteLLM route. The native worker's loopback guard and the forwarder's loopback listener belong to different pod contexts.

LiteLLM is the model gateway, not the model, agent or complete harness. The context-forwarder is inference middleware for request/context handling and owned-cache coordination; it is not the agent's durable memory. `deepinfer-dspark` and `sglang-dspark` are alternative model-serving backends, not serial agent stages. Current endpoints, image digests and physical placement require dated runtime evidence. See component map.

## Terms that require a specific mechanism

| Term | Required distinction |
| --- | --- |
| Tool / MCP integration | A callable action or integration interface; its presence does not authorize every action or make its server trusted. |
| Skill | Task-specific instructions and resources loaded when relevant; distinguish them from the callable tool implementing an action. |
| Hook | A mechanism invoked at an identified lifecycle event. A prompt rule, proxy check or periodic job is not automatically a lifecycle hook. |
| Policy enforcement point | Name the actual gateway, guard, broker, network policy or identity check. Use guardrail only with its mechanism and scope. |
| Sandbox / isolation | State the actual process/container/pod, identity, mounts, privileges and network boundary. A private directory or an unverified pod template alone does not establish an effective sandbox. |
| Context management | Input assembly, compaction, offloading and retrieval. Specify the mechanism actually present; do not infer all of them from long-context support. |
| Durable state / memory | Files, checkpoints or records that survive the stated lifecycle. Distinguish workspace persistence, conversation history, reusable knowledge and an ephemeral model/KV cache. |
| Orchestration / delegation | Task coordination and handoff. Three independently evaluated routes are not proof that those agents collaborated or delegated to one another. |
| Evaluator / verification | A defined assessment against explicit criteria. A separate evaluator must actually run; self-review, a unit test and live end-to-end acceptance are distinct evidence. |
| Recovery / continuation | State the implemented retry, cancellation, resume or restart behavior and its limits. A supervisor keeping a process alive does not prove successful task recovery. |
| Super-agent | Legacy roadmap label retained in existing identifiers. Prefer advanced orchestration roadmap in explanatory prose; it is not an additional accepted agent or a model capability claim. |

## Security and evidence stay explicit

The three risk objectives remain: **prevent external leakage; prevent damage or excessive access; keep results contained**. Harness mechanisms and platform/infrastructure enforcement contribute to these objectives at different boundaries. Prompt adherence is not infrastructure enforcement. The OWASP Agentic Top 10 mapping remains a risk classification, not certification.

Use separate evidence states: design; implemented in named source; tested locally for a stated behavior; built/CI checked; deployed at an identified revision/image; published and served with matching content; live behavior verified for the named route; accepted against the stated criteria. Do not promote one state from another. Current feature evidence and native SDK failures remain authoritative; terminology edits create no new passing tests or live acceptance.

## Editorial rules

Use MultiHarness consistently in prose. Preserve product names, filenames, URLs, feature IDs, service/resource names, historical quotations and original reference files. Label comparisons as integration routes and identify each route's native abstraction. For every diagram, distinguish logical roles, deployment boundaries and dated live observations. For every feature, connect intended behavior, implementing component, risk objective and exact evidence. Retained older diagrams are source/design views unless their own receipts establish more.
