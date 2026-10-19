# DSH User Manual

Use DSH in your browser to work with code, documents and analysis tools. This manual brings the everyday workflow, environment design, risk controls, administration, installation and measured inference results together. Start with the guided tour or follow the chapters below.

## 1 Get started

1. Open the DSH address supplied by your administrator. The floating **User manual** button opens this guide before sign-in.
2. If you are new, select **Create account**, choose a unique username and confirm a password of at least 12 characters. Then enter your local DSH username and password. Your DSH login selects your private workspace; it is separate from an AD or Kerberos login.
3. Leave **No Internet / Internal** selected for internal work. **Internet** is a separate environment for approved users preparing packages or working with public material.
4. Choose **DSH workspace**, **Web Terminal** or **JupyterLab** in **Open after sign in**, then sign in. For DSH, select a workspace and start a conversation. Give the assistant a bounded task and identify the files it should use.
5. Inspect its answer and saved outputs. Ask it to verify changes before relying on a result.

Anyone reaching the login page can create an account while private capacity is available. Signup assigns an exclusive No Internet/Internet runtime pair, but Internet access stays denied until an administrator grants it. A full pool refuses signup without creating an account. See [Create an account and approve Internet access](SELF_SERVICE_SIGNUP.html) for the complete flow.

### Custom app URLs and ports

The Create account count means **new-user slots**, not multiple workspaces for one user. It refreshes from current assignments; an unavailable refresh shows no old number. Your project folders and registered app names are separate concepts. See [capacity and monitoring](PLATFORM_CAPACITY_AND_CLIENTS.html).

Open `/applications` after signing in to save a friendly name for a port in your private environment. The notebook suggestion is `<username>-jupyter` on port 8888. Other app names/ports are configurable with collision checks. Login and tool navigation from a custom app hostname use the main DSH address. See [application URLs and Ingress setup](APP_URLS_AND_INGRESS.html) for path URLs, approved hostnames, TLS/DNS, wildcard behavior and publication commands.

### Pick the correct environment

| What you want to do | Where to work | What stays separate |
|---|---|---|
| Review internal files, code or analysis | No Internet / Internal | Your private files, conversations, attachments and credentials |
| Download approved dependencies or work with public resources | Internet, after approval | Its own private files and conversations; it does not mount your No Internet workspace |
| Make a dependency available offline | Internet download → operator approval → read-only approved cache | Package artifacts move through the approval path; protected projects and credentials do not |

Logout and sign in again to change environments. Switching does not copy conversations, files or credentials. No Internet restricts the local execution environment; a job submitted to another compute platform follows that platform's network and access rules.

## 2 Work with chats, projects and files

Keep related files in a project beneath `/workspace`. Select that project's working directory before asking for file operations. Attach only the documents needed for the task, or name the relevant files already in the workspace.

Start with a request such as: “Read README.md and identify the entry point, configuration files and test command. Cite the files you inspected. Do not edit anything yet.” For a change, state the desired behavior, allowable files and how the result should be checked.

Continue the same conversation for related work. Start another session for an unrelated task. Durable conversations and attachments remain in their assigned user's environment; another user's login does not inherit them. Refreshing the browser is different from starting a new conversation.

The shared model supports a total budget of 1,048,576 tokens, including instructions, tools, conversation, output and reserve. A short prompt in a large existing conversation can still require substantial processing. Near-1M cold preparation is expensive. Requests above the long-admission threshold are serialized; ordinary requests can continue alongside them. `/compact` reduces conversation history when useful; it does not increase the model's total budget.

## 3 Run tools and inspect results

DSH, Claude Code, Kilo and TrueForge load the same [platform guide](SHARED_PLATFORM_GUIDE.html) for environments, storage, applications and managed inference. Their conversations remain separate. The guide supplies context; the live gateway controls actual account and app permissions.

For Python notebooks, run `jupyter lab` in your terminal and open `/proxy/8888/lab` on this DSH site. Create a Python 3 notebook and run `print(6 * 7)`. Save it under `/workspace`; stop unused kernels when finished. Jupyter uses the selected environment's private storage, permissions and network controls. See [JupyterLab usage and setup](JUPYTERLAB.html).

Use the web terminal from the selected environment to inspect files and run commands. The terminal executes inside your assigned runtime, not on the Kubernetes node. Its processes have the same file permissions and network restrictions as the assistant's tools.

For a generated HTML result, serve only the result directory through an approved port and open its authenticated preview. Stop the server after use. Keep source files separate from generated results, review diffs and do not place passwords or tickets in prompts, repositories or exported reports.

The practical examples below cover repository review, CSV analysis, previews, package transfer, managed clients, Kerberos and the administrator overview.

## 4 Understand the three risk controls

The controls act at the network, execution/storage and authenticated access boundaries. The following chapters explain what each prevents and which connected systems enforce their own permissions.

## 5 Admin tasks and account lifecycle

An administrator opens `/admin` to review accounts, enable or disable access, sign out gateway sessions and grant or revoke Internet permission. In **Applications**, view all main users' app names and environment ports, edit ports, disable/re-enable or remove URL mappings, and set each user's **Name limit**. The default is **8**, shared across both environments; there are no approval tiers. Lowering a limit preserves existing URLs, files and histories. **My apps** shows each user's usage and effective limit. See the [admin application procedure](ADMIN_USAGE_TELEMETRY.html) and [recorded walkthrough](ADMIN_APPLICATIONS_WALKTHROUGH.html). Users can self-register, or an admin can create an account from available private-pair capacity. Use **Allow Internet** or **Disable Internet** beside an account to approve or revoke that separate permission. Revoking gateway access closes tracked connections; it does not cancel a tool already running inside an execution environment.

Use the usage panels to distinguish stored histories from active browser sessions, queued messages from running agents, and cumulative token counts from decoding speed. Storage figures belong to the selected runtime scope. Recorded token rates are not live GPU utilization and do not include every separately launched client.

Users change their own password through the password-change flow. An admin role grants operational oversight, not automatic ownership of private conversations. Keep any explicitly authorized support copy separate from the owner's original data.

Reload **User management** to see a newly registered account. Unused prepared pairs are available signup capacity; assigned pairs appear in account-scoped usage. Disabling an account preserves its private data and does not recycle the pair.

### Managed Jupyter and app startup

An administrator can approve persistent startup definitions in **Admin overview → Managed startup services**. Saving a definition leaves a new service stopped. Start enables automatic startup after a worker pod replacement; Stop prevents it. Restart replaces the managed process. This is separate from URL names, ports and quota management. Saved notebooks and files persist, while memory-only kernel state does not.

See [managed startup, architecture, user isolation and credentials](APP_SERVICE_SUPERVISION.html) and the [recorded lifecycle walkthrough](APP_AUTOSTART_WALKTHROUGH.html). Each user has separate No Internet and Internet runtime pods; the supervisor runs non-root inside that user's selected pod. It receives no gateway password store, agent history mount, launch token or model-key environment. Approved apps share their owner's workspace and runtime permissions.

## 6 Troubleshoot common situations

| Symptom | What to check |
|---|---|
| Your sign-in session ended | Keep the draft tab open. Select **Sign in again**, authenticate in the new tab with the same account and environment, then return and select **I have signed in**. Submit the draft yourself; DSH does not replay a failed prompt. An older tab loaded before this recovery control was installed needs one reload after you copy its unsent draft. |
| Internet choice is disabled | Check credentials and request an Internet grant from the administrator. Do not change endpoint or routing settings to bypass it. |
| A web tool exists but public access fails | No Internet policy applies to tools as well as terminal commands. Use approved internal destinations or the separate Internet environment for public work. |
| Files or chats seem missing | Verify username, selected environment and project. Internet and No Internet histories are separate. |
| A short question is slow | Check the conversation's accumulated context, tool work and long-request queue. Use a fresh session for an unrelated small task. |
| A package is unavailable offline | Request the download/approval workflow; an Internet workspace cannot directly install into your protected workspace. |
| An analysis claims unsupported facts | Ask for exact source files/sections, verify them and rerun the bounded task. Context capacity alone does not guarantee analytical accuracy. |
| A datalake operation fails | Check your own Kerberos authentication and data-platform permission. DSH login does not grant datalake rights. |

## 7 Performance and stress-test results

Read preparation latency, streaming speed and total throughput separately. A configured concurrency ceiling is not a promise of simultaneous full-1M requests. The recorded accepted profile and workload-specific measurements follow; operator reruns belong in the test record.

## 8 Install and operate DSH

The following operator walkthrough covers prerequisites, private inputs, images, storage, identity, routing, network policy, verification and rollback. Run it from the repository root using the stated shell. Supply site-specific values privately.

DSH, LiteLLM and GPU inference need not share a machine. Choose a same-cluster Service route, a separate GPU backend FQDN, or an approved relay to remote LiteLLM. Keep the managed-client policies and No Internet boundaries consistent. See [deployment topology, endpoint forms and setup steps](FLEXIBLE_DEPLOYMENT.html).

## 9 LLM and GPU setup

This final chapter covers the shared local inference stack and its client budgets. The model is shared; user workspaces and credentials are not.
