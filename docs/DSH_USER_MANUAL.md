# DSH User Manual

[Terminology: agent, harness and shared platform](HARNESS_TERMINOLOGY.html). Compare agent integration routes while preserving SDK, harness and infrastructure distinctions.


Current DSH guide and PowerPoint


Use DSH in your browser to work with code, documents and analysis tools. This manual brings the everyday workflow, environment design, risk controls, administration, installation and measured inference results together. Start with the guided tour or follow the chapters below.



### Learn with the video courses



Open the DSH video course for English chapters, captions, section navigation and reproduction examples. Its contents page lists the published lessons; the GPU portal hosts its own technical course. See the course guide and navigation video. Keep using the current package guide for self-service Python environments.


## 1 Get started



Successful signup enables your private **No Internet / Internal** workspace immediately, without individual administrator approval. **Only Internet access requires a separate administrator grant.** Account capacity controls are not an approval queue.



1. Open the DSH address supplied by your administrator. The floating **User manual** button opens this guide before sign-in.

2. Choose **Local DSH account** for a provisioned DSH account or **AD / LDAP** for your corporate identity. With AD / LDAP, use your short username or the approved corporate UPN or `DOMAIN\username` form. Use the same provider and identity format when signing in through a protected application URL. For a new Local account, select **Create account**, choose a unique username and confirm a password of at least 12 characters. If an AD name already exists as a Local account, contact the administrator; DSH refuses the collision instead of merging files or histories. Workspace sign-in does not create a Kerberos ticket for datalake execution.

3. Leave **No Internet / Internal** selected for internal work. **Internet** is a separate environment for approved users preparing packages or working with public material.

4. Choose **DSH workspace**, **Web Terminal** or **JupyterLab** in **Open after sign in**, then sign in. For DSH, select a workspace and start a conversation. Give the assistant a bounded task and identify the files it should use.

5. Inspect its answer and saved outputs. Ask it to verify changes before relying on a result.



Anyone reaching the login page can create an account while private capacity is available. Signup assigns an exclusive No Internet/Internet runtime pair, but Internet access stays denied until an administrator grants it. A full pool refuses signup without creating an account. See Create an account and approve Internet access for the complete flow.



### Use one private project across the tools



Save a notebook and text file under `/workspace`, read them in Web Terminal, then ask DSH's file tools to read them and save an output in the same project. Reopen that output in Jupyter. All three use the same private files for your selected account and environment; choose that project separately in each tool. Claude Code, Kilo and TrueForge share the platform guide and project files while keeping separate conversations. An approved internal Git repository can be cloned with verified TLS and your own authorized authentication while public Internet stays off. See the step-by-step workflow and fresh-signup checks.



### Custom app URLs and ports



The Create account count means **new-user slots**, not multiple workspaces for one user. It refreshes from current assignments; an unavailable refresh shows no old number. Your project folders and registered app names are separate concepts. See capacity and monitoring.



If the count is zero, the administrator checks **Account capacity and automatic provisioning**. There is no account limit (removed 30 Oct 2026); sign-ups pause only when local storage would fall below the 200 GiB reserve. Disabled accounts retain their data and capacity assignment; they are not silently recycled.



Open `/applications` after signing in to save a friendly name for a port in your private environment. The notebook suggestion is `<username>-jupyter` on port 8888. Other app names/ports are configurable with collision checks. Login and tool navigation from a custom app hostname use the main DSH address. See application URLs and Ingress setup for path URLs, approved hostnames, TLS/DNS, wildcard behavior and publication commands.



### Pick the correct environment



| What you want to do | Where to work | What stays separate |

|---|---|---|

| Review internal files, code or analysis | No Internet / Internal | Your private files, conversations, attachments and credentials |

| Download approved dependencies or work with public resources | Internet, after approval | Its own private files and conversations; it does not mount your No Internet workspace |

| Make a dependency available offline | Internet download → operator approval → read-only approved cache | Package artifacts move through the approval path; protected projects and credentials do not |



Logout and sign in again to change environments. Switching does not copy conversations, files or credentials. No Internet restricts the local execution environment; a job submitted to another compute platform follows that platform's network and access rules.



### Select a project in the updated workspace picker



If a fresh runtime shows **Choose workspace**, use **Add workspace**, then **Edit path**. Enter your project directory beneath `/workspace`, press Enter and select **Open**. Registering a workspace makes that directory available in the sidebar; it does not move files or copy another environment's history. Empty, never-used sessions can appear as **New Session**. Use the registered project and session search to find existing conversations.



Sign in once with your team identity. Managed LiteLLM profiles hide the official DeepSeek account sign-in; the approved model connection is already configured. Team login, private routing and Logout remain available. See [team login and managed model access](MANAGED_PROVIDER_LOGIN.html).

## 2 Work with chats, projects and files



Keep related files in a project beneath `/workspace`. Select that project's working directory before asking for file operations. Attach only the documents needed for the task, or name the relevant files already in the workspace.



Start with a request such as: “Read README.md and identify the entry point, configuration files and test command. Cite the files you inspected. Do not edit anything yet.” For a change, state the desired behavior, allowable files and how the result should be checked.



Continue the same conversation for related work. Start another session for an unrelated task. Durable conversations and attachments remain in their assigned user's environment; another user's login does not inherit them. Refreshing the browser is different from starting a new conversation.



The shared model supports a total budget of 1,048,576 tokens, including instructions, tools, conversation, output and reserve. A short prompt in a large existing conversation can still require substantial processing. Near-1M cold preparation is expensive. Requests above the long-admission threshold are serialized; ordinary requests can continue alongside them. `/compact` reduces conversation history when useful; it does not increase the model's total budget.



## 3 Run tools and inspect results



Approved startup services run in a separate supervisor container. Keep their dependencies in the pinned runtime image or an approved project-local installation visible in the owner workspace. Packages installed only in DSH's temporary container directories are not automatically shared with that container.



DSH, Claude Code, Kilo and TrueForge load the same platform guide for environments, storage, applications and managed inference. Their conversations remain separate. The guide supplies context; the live gateway controls actual account and app permissions.



Within the same account and environment, DSH, Web Terminal, Jupyter and the installed coding clients see the same mounted `/workspace` files. This does not synchronize their current directories: select the project in DSH, use `cd /workspace/<project>` in the terminal, and open the matching folder in Jupyter. Other users and the opposite environment have separate storage.



An approved internal Git service can remain available in No Internet. Use its operator-supplied HTTPS address and normal private authentication; keep TLS verification enabled. Internal Git permission does not grant public Internet access. If DNS, trust or repository authorization fails, ask the operator to check that specific service. Do not put passwords or PATs in a clone URL, prompt or notebook. Internal Git setup.



For Python notebooks, choose **JupyterLab** at sign-in or open its authenticated notebook link. In Main DSH, DSH2 and DSH3, opening Jupyter starts it when needed and reuses any running server and kernels. DSH2 and DSH3 use their assigned owner account and Internet environment. Internet still needs a separate administrator grant, and administrator service restrictions remain in force. A worker restart ends in-memory kernels; saved notebooks remain in your private workspace. Create a Python 3 notebook and run `print(6 * 7)`. Save it under `/workspace`; stop unused kernels when finished. Jupyter uses the selected environment's private storage, permissions and network controls. See JupyterLab usage and setup.


Use the web terminal from the selected environment to inspect files and run commands. The terminal executes inside your assigned runtime, not on the Kubernetes node. Its processes have the same file permissions and network restrictions as the assistant's tools.



For a generated HTML result, serve only the result directory through an approved port and open its authenticated preview. Stop the server after use. Keep source files separate from generated results, review diffs and do not place passwords or tickets in prompts, repositories or exported reports.



The [worked examples](DSH_PLATFORM_GUIDE.html#example-usage) cover repository review, CSV analysis, previews, package transfer, managed clients and private authentication.



### Install private Python packages



Open **My apps → My Python environments**. With an existing administrator Internet grant, request pinned Python wheels and receive a new private No Internet environment plus a Jupyter kernel. A separate downloader has no protected workspace; installation runs with no network access. Other users, the opposite environment, histories and existing installations remain unchanged. See the step-by-step package guide and captioned walkthrough. Unsupported packages still use the operator-reviewed cache/image process.



## 4 Understand the three risk controls



The controls act at the network, execution/storage and authenticated access boundaries. Read [the three risk controls](DSH_PLATFORM_GUIDE.html) for each mechanism and the responsibilities on connected systems.



For an app-focused DSH sign-in page, use your normal DSH identity. If the app instead shows **Continue with your normal DSH login**, sign in through its link and return to the original app tab; use **I have signed in — continue** if needed. Public mappings skip the DSH gate but may retain the app's own login. RegChat is an example mapping. See [application sign-in and return](APP_SIGNIN_AND_RETURN.html).

## 5 Admin tasks and account lifecycle



An administrator opens `/admin` to review accounts, enable or disable access, sign out gateway sessions and grant or revoke Internet permission. In **Applications**, view all main users' app names and environment ports, edit ports, disable/re-enable or remove URL mappings, and set each user's **Name limit**. The default is **8**, shared across both environments; there are no approval tiers. Lowering a limit preserves existing URLs, files and histories. **My apps** shows each user's usage and effective limit. See the admin application procedure and recorded walkthrough. Users can self-register, or an admin can create an account from available private-pair capacity. Use **Allow Internet** or **Disable Internet** beside an account to approve or revoke that separate permission. Revoking gateway access closes tracked connections; it does not cancel a tool already running inside an execution environment.



Use the usage panels to distinguish stored histories from active browser sessions, queued messages from running agents, and cumulative token counts from decoding speed. Storage figures belong to the selected runtime scope. Recorded token rates are not live GPU utilization and do not include every separately launched client.



Users change their own password through the password-change flow. An admin role grants operational oversight, not automatic ownership of private conversations. Keep any explicitly authorized support copy separate from the owner's original data.



In User management, **Disable** applies to the named account: it blocks sign-in while retaining files and history. It does not disable the platform. **Disable Internet** changes Internet permission; **Stop** in Managed startup services controls a named app. Read the account or service name before confirming. **Cancel** leaves the requested change unapplied.



Reload **User management** to see a newly registered account. Unused prepared pairs are available signup capacity; assigned pairs appear in account-scoped usage. Disabling an account preserves its private data and does not recycle the pair.



### Account capacity and automatic provisioning



Open **Admin overview → Account capacity and automatic provisioning**. Set the desired warm spares, then save; there is no account limit. The default spare target is **two**. A separate provisioner prepares new private pairs after signup consumes capacity; the gateway receives no Kubernetes management token. Pause replenishment for maintenance without deleting accounts, files or histories. Existing extra spares are retained when targets are lowered. See the capacity architecture, setup and walkthrough.



### Managed Jupyter and app startup



New accounts receive the built-in Jupyter service automatically after No Internet assignment. **Admin overview → Managed startup services** controls it and additional custom commands. Saving a new custom definition leaves that service stopped. Start enables automatic startup after a worker pod replacement; Stop prevents it. Restart replaces the managed process. This is separate from URL names, ports and quota management. Saved notebooks and files persist, while memory-only kernel state does not.



See managed startup, architecture, user isolation and credentials and the recorded lifecycle walkthrough. Each user has separate No Internet and Internet runtime pods; the supervisor runs non-root inside that user's selected pod. It receives no gateway password store, agent history mount, launch token or model-key environment. Approved apps share their owner's workspace and runtime permissions.



## 6 Troubleshoot common situations



Browser sign-in lasts up to 24 hours and survives a gateway restart. Logout, an administrator's session revocation, account disablement or a password change invalidates the affected sign-in. Terminal and application WebSockets close when their session expires or is logged out. A disconnected browser does not delete files or history, or automatically cancel an agent; use Stop for the active conversation turn.



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



## Appendix A — Performance and stress-test results



Use **Stop** to cancel the active conversation turn, including long preparation or a queued model request. Closing the browser keeps a persistent agent running. Stop does not delete saved history or project files. Long requests share one active position and one waiting position; further requests receive a busy response while ordinary short requests remain eligible to run.



Read preparation latency, streaming speed and total throughput separately. A configured concurrency ceiling is not a promise of simultaneous full-1M requests. Use the [technical appendix](DSH_PLATFORM_GUIDE.html#appendix-b) and LLM results guide for dated accepted profiles, workload-specific measurements and ongoing trials.



## Appendix B — Install and operate DSH



Platform installation and recovery procedures are maintained in internal operator documentation.



DSH, LiteLLM and GPU inference need not share a machine. Choose a same-cluster Service route, a separate GPU backend FQDN, or an approved relay to remote LiteLLM. Keep the managed-client policies and No Internet boundaries consistent. See deployment topology, endpoint forms and setup steps.



## Appendix C — LLM and GPU setup



This final chapter covers the shared local inference stack and its client budgets. The model is shared; user workspaces and credentials are not.



### DSH2 and DSH3 managed startup



In the main **Admin overview → Managed startup services**, select **Runtime → DSH2** or **DSH3**. The existing owner and Internet environment are fixed. Save/start **jupyter** for notebooks; save a supported workspace command and explicit app port for a user app. Stop disables automatic restart, including after pod replacement. These instances keep their own owner login, storage and histories; registering a startup target does not grant main-platform login or file access. The owner's existing authenticated Jupyter/app URLs remain in use.



See the startup architecture and installation guide and recorded target-selector workflow. Saved notebook/data files persist; unsaved kernel memory and interrupted computations do not resume automatically.



## Managed agent tasks and Web Terminal kubectl

The deployed [Agent runtime and execution backend](AGENT_RUNTIME_AND_EXECUTION_BACKENDS.html) page lets an authenticated user select DSH Python SDK, Claude Code or Deep Agents independently from the execution backend. The private DSH workspace is enabled. OpenShell is visible but remains disabled until all 25 Test gates and rollback qualification pass. Broker health, authentication and capability mapping are verified; guarded model execution for each runtime still requires bounded live acceptance.

Web Terminal includes the pinned, checksum-verified `kubectl` v1.32.9 client. The user workspace has no automatic service-account token or default kubeconfig, so the binary grants no cluster access by itself. Cluster access requires a separately approved least-privilege kubeconfig for the specific task.

## Quick actions menu

A launcher button at the bottom right of every DSH page (a round gear icon, named Quick actions) opens a small menu with Web Terminal, JupyterLab, Agent tasks, Admin overview (administrators only), My apps, Credentials (when enabled) and Logout. The menu closes with Esc, with a click elsewhere, or after you choose an item.

If a DSH page shows "Reconnecting..." or "Loading models..." for more than a minute, for example after a service update, reload the page. If it persists, sign out and sign in again; your files are kept.

## Documentation library



Use the [three-risk platform guide](DSH_PLATFORM_GUIDE.html) for the design, the [complete documentation library](index.html) for setup and feature guides, and the [English course](/manual/course/) for the narrated walkthrough.



## 1M context and current speed

> **Current speed (30 Oct 2026, one standard).** DeepInfer 1M in production, decode rate D per user: 57.8 tok/s on a fixed 512-token essay (W1) and 62.1 on free text (W4) for one user; at 16 clients 384 (W1) and 421 (W4) tok/s in total. SGLang (rollback engine): 67.6 (W1) and 68.0 (W4) for one user, 126 and 145 in total at 16 clients. One user: on 30 Oct SGLang was about 9–17 % faster; same-day 31 Oct–1 Nov: about 7–9 % faster (61.8 vs 58.0 and 69.0 vs 63.1); many users: DeepInfer gives about 3× the total. Definitions, method and every result: LLM speed comparison. Newer capacity measurements (9 Nov 2026), with decode slots and concurrency: capacity report.

Instructions, tool definitions, history, input and reserved output share one **1,048,576-token** budget. The model serves up to eight requests at once (two per GPU); further requests wait their turn.

For everyday use, continue a related conversation when its context is useful, start a fresh session for an unrelated short question, and review cited sources and tool outputs. Use Stop to cancel long preparation or queued work. Longer context preserves more material; it does not guarantee a faster or more accurate answer.

Speed comparison, including the SGLang baseline.


## Jupyter Start controls

**Start is safe to repeat:** an already-enabled managed Jupyter service keeps its
process, restart counter, notebooks and kernel variables. Start enables a stopped
service; Restart and Stop deliberately interrupt its kernels and retain their
confirmation prompts. See [administrator steps and behavior](JUPYTER_START_CONTROLS.html)
and the [captioned walkthrough](JUPYTER_DSH2_DSH3_WALKTHROUGH.html).


## Application links, slides and English video

Use the [application links and Main/Test guide](APP_LINKS_AND_STATUS.html) to distinguish Main workspaces and application controls from the App5/App6 Test fixtures. It links the current slides and English video, explains normal DSH sign-in and return to the original app tab, and distinguishes Public routing from a destination application's own login.


## Site compatibility and everyday use

Main DSH, DSH2 and DSH3 use the same approved DSH application build (0.2.2-rc.1 in the source) and managed inference transport. As of 10 Nov 2026 the private workspaces of Main DSH run that build; the gateway and controllers still run the 30 Oct base image and receive current source through ConfigMaps. Main DSH provides team accounts and private user/environment routing. DSH2 and DSH3 retain their owner-only authentication and Internet-only site settings. These settings do not require separate forks of the DSH application.

1. At sign-in, choose **AD / LDAP** for a corporate account or **Local DSH account** for a provisioned local account. A local account must use the local option.
2. In a conversation, select **DeepSeek-V4.1-Flash** from the managed **LiteLLM** provider. DSH saves an owner's model choice for subsequent requests. The official DeepSeek provider sign-in is separate from the team's workspace login.
3. Administrators enable automatic startup only for approved applications. **Start** keeps an already-running service; **Restart** replaces that service process; **Stop** prevents automatic restart. Saved files and histories persist, while unsaved process memory and notebook variables do not survive a real restart.

The 24 October checks verified normal owner login and exact managed-model replies on all three sites. Isolated supervisor checks covered startup, automatic recovery, explicit restart, Stop and access revocation without restarting existing applications. The source qualification also exercised a separate Jupyter notebook/kernel, authorization and XSRF fixture. See version and maintenance checks.

<!-- credential-management-design -->

## User-managed credentials

User-managed credentials: users enter secrets through a dedicated settings form, while the harness receives only aliases. A separate broker checks the owner, workspace, environment, destination and action before using the secret. Consequential actions require bound approval; audit logs exclude secret values. Implemented for configured API-token/PAT connectors; OAuth consent and Kerberos acquisition are not included. Read the [credential management guide and Fola video](USER_CREDENTIAL_MANAGEMENT.html).
