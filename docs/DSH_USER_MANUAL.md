# DSH User Manual

Use DSH in your browser for code, documents and analysis. Start with the private No Internet environment, then open the workspace, terminal, notebook or application your task requires. Your operator supplies the site address and enables the features described below.

## 1 Sign in or create an account

1. Open your DSH site and choose **Local DSH account** or **AD / LDAP** when the directory option is enabled.
2. For AD / LDAP, enter your short username, approved corporate UPN or `DOMAIN\username` form. Use the same provider and identifier when signing in through a protected application URL. Your organization configures the accepted domain.
3. For a new local account, use **Create account** where registration is enabled. Supply a unique name and a password meeting the site's policy. Capacity checks may temporarily stop registration; existing users can continue signing in.
4. Leave **No Internet / Internal** selected. Internet access is a separate administrator grant; registration is not an Internet-approval request.
5. Choose **DSH workspace**, **Web Terminal** or **JupyterLab** in **Open after sign in**, then sign in.

An AD identity that conflicts with an existing local username is refused for administrator review. DSH does not automatically merge identities, replace passwords or assign another identity's history. Keep using the existing local sign-in until the administrator resolves ownership and preserves the required data. See [AD identity and collision rules](LDAP_AUTHENTICATION.md).

Sign in once with your team identity. Managed LiteLLM profiles hide the official DeepSeek account sign-in; the approved model connection is already configured. Team login, private routing and Logout remain available. See [team login and managed model access](MANAGED_PROVIDER_LOGIN.html).

## 2 Work with chats and files

Select a project workspace and start a conversation. Describe a bounded task, identify the files to use and review the proposed changes and saved outputs. Keep durable work in the workspace location supplied by your operator.

Each provisioned user/environment has its own execution and storage boundary. Internet and No Internet environments have separate files, history, attachments and credential state. Shared model inference does not grant access to another user's files. Switching environment does not copy your conversation or project automatically.

Persistent files and settings can survive a worker replacement. Running processes and in-memory notebook variables require separate recovery; persistence is not a backup. Use the operator's backup and restoration process for deleted content.

## 3 Use the terminal, notebook and coding clients

Open **Web Terminal** or **JupyterLab** from your authenticated site. They execute with your assigned workspace identity and environment permissions. Terminal access does not grant administrator or cluster-management rights. See [on-demand notebooks and the captioned guide](JUPYTER_ON_DEMAND.md).

Use the installed managed entry points for Claude Code, Kilo Code or TrueForge where your operator has enabled them. Client configuration and supported features can differ; see [client compatibility](LIVE_CLIENT_COMPATIBILITY.md) and [managed-client validation](MANAGED_CLIENT_VALIDATION.md). DSH and these clients use the configured shared model route rather than a separate GPU copy per user.

Keep credentials out of prompts, shared files and reports. DSH sign-in does not create a Kerberos ticket or grant datalake permissions. Use the approved private authentication process for any separate data service.

## 4 Publish an application URL

Open **My applications**, select an available name, and register your application's port or an approved external HTTPS destination. A saved URL does not start a server, install DNS or enable Internet access.

Use **Require DSH sign-in** for private applications. Public access is an explicit choice for an approved mapping; it must not be used for protected data. An external application's own authentication remains separate from the DSH gateway session.

To share an ordinary local web app, keep **Require DSH sign-in** and choose **Any enabled DSH account — shared application**. JupyterLab and terminal ports remain owner-only. Sharing exposes only the selected application; its own permissions and write actions still apply. See [sharing and isolation](AUTHENTICATED_APP_SHARING.html).

The administrator controls the per-user name limit, allowed domains, reserved names and available hostname/path routes. Opening Jupyter in Main DSH or the configured DSH2/DSH3 sites starts it when needed and reuses a running server and kernels. The owner-only sites keep their assigned Internet environment. Internet approval and administrator service restrictions still apply. A worker restart ends in-memory kernels; saved notebooks remain in the private workspace. Other application restart requires an administrator-approved service configuration; unregistered processes are not automatically relaunched. See [application URLs, routing and restart controls](APP_PROXY.md).

For an app-focused DSH sign-in page, use your normal DSH identity. If the app instead shows **Continue with your normal DSH login**, sign in through its link and return to the original app tab; use **I have signed in â€” continue** if needed. Public mappings skip the DSH gate but may retain the app's own login. RegChat is an example mapping. See [application sign-in and return](APP_SIGNIN_AND_RETURN.html).

## 5 Prepare packages for No Internet work

Where self-service packages are enabled, use **My Python environments**:

1. Obtain the administrator's Internet approval for your account. You can keep your interactive session in No Internet; an isolated Internet job performs the download.
2. Enter a new environment name and one to eight exact package pins such as `six==1.17.0`.
3. Select **Download and install privately** and follow the request status. Only one package request can run for your account at a time.
4. The service downloads supported Python wheels, validates the artifacts and installs them offline into a new private No Internet virtual environment. Existing environments remain unchanged.
5. When the request completes, use the displayed Python path or select its named Jupyter kernel.

This self-service wheel path does not require an operator to promote every request manually. Source builds, direct URLs and startup `.pth` hooks require operator review. For separately maintained shared packages, the operator can review and promote artifacts from incoming staging into an approved read-only cache.

The two workspaces remain separate; the Internet job does not receive a writable mount of the protected workspace. Do not copy protected prompts, datasets or credentials into Internet staging. See [the three risk controls](THREE_RISK_CONTROLS.html).

## 6 Use shared long-context inference

The conversation, attached content and tool definitions all consume context. A configured 1M ceiling does not mean every request uses one million tokens. Output space also counts toward the total budget.

Large requests use admission control and may wait or receive a busy response while ordinary requests remain schedulable. A shared ceiling does not guarantee simultaneous maximum-length requests or a particular token rate. Follow the operator's qualified limits and compaction policy. See [1M context operation](CONTEXT_1M.md) and [GPU setup](../gpu-stack/README.md).

## 7 Administrator tasks

Use the central dashboard to manage named accounts, enable or disable access, approve or revoke Internet access, sign out sessions, and inspect application assignments, limits and capacity where those controls are installed. Use the site's administration identity rather than another user's workspace credentials.

Access logs provide operational visibility. Do not assume they contain every terminal command, prompt, file change or remote data-platform action. Infrastructure monitoring, retention and data-service authorization require their configured integrations. See [capacity and signup](SIGNUP_CAPACITY.md), [security boundaries](SECURITY.md) and [installation](INSTALL.md).

## 8 Help, learning and sign out

Use the site's **User manual** link, documentation library and available course player. The [course guide](COURSE_DELIVERY.md) explains video, captions and slide companions. On a companion page, select **Download PowerPoint (.pptx)**, save the file and open the saved presentation. See [slide downloads](SLIDE_DOWNLOADS.md).

Use **Logout** when finished. If a session expires, sign in again before retrying. Check your current draft and task state before resubmitting work. Contact the administrator for an identity conflict, unavailable runtime or repeated access failure; do not share your password in the support conversation.


## 1M context, concurrency and measured speed — 24 October 2026 (historic, SGLang)

> **Current speed (30 Oct 2026, one standard).** DeepInfer 1M in production, decode rate D per user: 57.8 tok/s on a fixed 512-token essay (W1) and 62.1 on free text (W4) for one user; at 16 clients 384 (W1) and 421 (W4) tok/s in total. SGLang (rollback engine): 67.6 (W1) and 68.0 (W4) for one user, 126 and 145 in total at 16 clients. One user: SGLang is about 9–17 % faster; many users: DeepInfer gives about 3× the total. Definitions, method and every result: [LLM speed comparison](https://github.com/skunpoj/dsh_setup/blob/main/docs/deepseek-v41-h100/README.md#current-production-30-oct-2026-utc). The figures below are historic SGLang measurements with their own workloads and timing boundaries.

The recorded main DSH tests demonstrate a 1,048,576-token total context budget. Instructions, tool definitions, history, input and reserved output share that budget. One request above 128K input is admitted at a time; ordinary short requests remain concurrent. The recorded backend cap of eight running requests does not mean eight maximum-size conversations fit.

| Recorded check | Measurement | Interpretation |
|---|---|---|
| Near-1M text capacity — trial R | 1,002,051 input + 636 output tokens; completed actual DSH turn | Capacity passed for this recorded workload. |
| Cold preparation — trial R | 29m 26.56s preparation; 29m 44.28s whole client turn | Preparation and total waiting time are separate from generation speed. |
| Long-answer generation — trial R | 61.56 output tokens/sec during the stream | A streaming-window rate; not whole-turn throughput. |
| Automatic compaction — trial W | 1,003,068 input → 885 summary output tokens; 1,664.07s native summary | The compaction operation completed. The following request used 196,968 input tokens. |
| Ordinary requests during compaction — trial W | 26 fully overlapping replies; median 6.09s, p95 10.23s, maximum 12.26s; zero retries | Short requests continued during the long workflow. |
| Summary generation — trial W | 71.80 output tokens/sec at the forwarding boundary; 1,748.95s whole client workflow | A different workload and timing boundary from trial R. |

Passed: recorded near-1M text capacity, automatic compaction, concurrent short replies, explicit reference checks, real tool operations and the scoped fixture-preservation checks. Durable files and histories are distinct from unsaved process or notebook-kernel memory.

Not established: 100+ output tokens/sec for a near-1M conversation, two simultaneous full-1M requests, or consistently accurate million-token analysis. The original ambiguous-reference check failed, and the original summary made an unsupported acceptance claim. Separate small-test fixes remain distinct from deployment and a full near-1M quality retest; they do not rewrite those failures.

The small follow-up used eight synthetic model requests and 26 component checks. The tested acceptance/status and identifier-recall cases passed, and the false missing-content claim was corrected. Actor attribution still failed: the summary credited the assistant guide with identifiers that appeared only in the user input. Overall summary faithfulness remains unaccepted. The prompt-only revisions did not pass actor-attribution verification; no near-1M retest or runtime restart was performed.

### Identifier-attribution checkpoint protection — 24 October 2026

The compaction guard is active on all 34 running workers across DSH, DSH2 and DSH3. It was loaded through DSH's supported profile hot reload, without restarting DSH, Jupyter or notebook kernels. Existing compaction instructions, checkpoint framing, model settings and storage mounts remain unchanged.

Before a future summary is adopted, the guard checks claims that the assistant included opaque identifiers against the actual user and assistant messages. For example, identifiers supplied only by the user cannot be credited to an assistant-produced guide. Unsupported or uncertain attribution holds compaction before checkpoint adoption, releases no successful candidate text and does not retry through recovery. Ordinary chat bypasses this check.

Verification passed 51 source/component checks for each repository-specific installer, six native compaction cases, and official file-watcher activation/removal checks. All 34 live workers passed four in-process synthetic checks each: ordinary-chat bypass, supported attribution, explicit unsupported attribution and unsupported “assistant guide” wording — 136 checks in total. These checks made no real model calls and did not repeat near-1M testing.

A memory-only native compaction produced a checkpoint that correctly attributed the identifiers to the user, retained the generic assistant guide and did not invent acceptance evidence: 4.673 seconds, 1,178 input / 407 output tokens. The initial four real-model requests included a leading-answer smoke check, a truncated neutral reply and an ambiguous origin field; their original results remain preserved. One later question explicitly asked which conversation speaker supplied the identifiers, using the same saved checkpoint and unchanged native framing. It returned the correct user role and a ten-word evidence quote that exactly matched the checkpoint: HTTP 200, 0.519 seconds, 557 input / 43 output tokens, complete stop. The question supplied no expected role or answer. This closes the specific speaker-origin ambiguity for that check; it does not establish general summary faithfulness. Five real-model requests are recorded in total, with zero client retries. No compaction or near-1M test was repeated, and no user session was persisted or changed.

Pod identities, container restart counts, existing plugin records and protected DSH/Jupyter process identities stayed unchanged. Existing history/attachment/workspace metadata fingerprints matched before and after each activation; these are metadata checks, not a new byte-by-byte audit of all user files. Only versioned guard files and one added profile entry were written.

The guard applies to compactions started after its activation; earlier summaries and already-started requests are unchanged. Its persistent profile entry and code remain available on the existing workers' state volumes. Brand-new workers using an older image still require the same activation or an image containing the committed build-time guard. The live add-on checks the tested English identifier-attribution patterns; it does not certify every summary statement. On a hold, review the affected conversation rather than treating the rejected summary as an accepted result. The original history is not replaced; rejected-candidate details remain on the in-memory error object.



For everyday use, continue a related conversation when its context is useful, start a fresh session for an unrelated short question, and review cited sources and tool outputs. Use Stop to cancel long preparation or queued work. Longer context preserves more material; it does not guarantee a faster or more accurate answer.

[Detailed dated results](GPU_TRIAL_STATUS_20261023.html).


## Latest verified interactive results

The 23 October 2026 check passed normal login, terminal commands, Jupyter kernel
execution and logout for Main DSH in both environments and the DSH2/DSH3 owner
workspaces. See the [verified results and preservation limits](JUPYTER_INTERACTIVE_VERIFICATION_20261023.html).
The executing capacity controller now includes the qualified finite-number guard;
see the verified results for the controller-only deployment scope.


## Jupyter Start controls

**Start is safe to repeat:** an already-enabled managed Jupyter service keeps its
process, restart counter, notebooks and kernel variables. Start enables a stopped
service; Restart and Stop deliberately interrupt its kernels and retain their
confirmation prompts. See [administrator steps and behavior](JUPYTER_START_CONTROLS.html)
and the [captioned walkthrough](JUPYTER_DSH2_DSH3_WALKTHROUGH.html).


## Current guide and lifecycle verification

See [document alignment](DOCUMENT_ALIGNMENT_20261023.md) for current controls, tests and historical-media limits.

## Application links, slides and English video

Use the [application links and Main/Test guide](APP_LINKS_AND_STATUS.html) to distinguish Main workspaces and application controls from the App5/App6 Test fixtures. It links the current slides and English video, explains normal DSH sign-in and return to the original app tab, and distinguishes Public routing from a destination application's own login.


## Site compatibility and everyday use

Main DSH, DSH2 and DSH3 use the same approved DSH 0.2.1-rc.2 application build and managed inference transport. Main DSH provides team accounts and private user/environment routing. DSH2 and DSH3 retain their owner-only authentication and Internet-only site settings. These settings do not require separate forks of the DSH application.

1. At sign-in, choose **AD / LDAP** for a corporate account or **Local DSH account** for a provisioned local account. A local account must use the local option.
2. In a conversation, select **DeepSeek-V4.1-Flash** from the managed **LiteLLM** provider. DSH saves an owner's model choice for subsequent requests. The official DeepSeek provider sign-in is separate from the team's workspace login.
3. Administrators enable automatic startup only for approved applications. **Start** keeps an already-running service; **Restart** replaces that service process; **Stop** prevents automatic restart. Saved files and histories persist, while unsaved process memory and notebook variables do not survive a real restart.

The 24 October checks verified normal owner login and exact managed-model replies on all three sites. Isolated supervisor checks covered startup, automatic recovery, explicit restart, Stop and access revocation without restarting existing applications. The source qualification also exercised a separate Jupyter notebook/kernel, authorization and XSRF fixture. See [version and maintenance checks](https://github.com/skunpoj/dsh_setup/blob/main/docs/THREE_SITE_SYNC_20261024.md).

<!-- credential-management-design -->

## User-managed credentials

User-managed credentials: users enter secrets through a dedicated settings form, while the harness receives only aliases. A separate broker checks the owner, workspace, environment, destination and action before using the secret. Consequential actions require bound approval; audit logs exclude secret values. Implemented for configured API-token/PAT connectors; OAuth consent and Kerberos acquisition are not included. Read the [credential management guide and Fola video](USER_CREDENTIAL_MANAGEMENT.html).
