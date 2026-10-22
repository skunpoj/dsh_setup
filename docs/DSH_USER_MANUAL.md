# DSH User Manual

Use DSH in your browser for code, documents and analysis. Start with the private No Internet environment, then open the workspace, terminal, notebook or application your task requires. Your operator supplies the site address and enables the features described below.

## 1 Sign in or create an account

1. Open your DSH site and choose **Local DSH account** or **AD / LDAP** when the directory option is enabled.
2. For AD / LDAP, enter your short username, approved corporate UPN or `DOMAIN\username` form. Use the same provider and identifier when signing in through a protected application URL. Your organization configures the accepted domain.
3. For a new local account, use **Create account** where registration is enabled. Supply a unique name and a password meeting the site's policy. Capacity checks may temporarily stop registration; existing users can continue signing in.
4. Leave **No Internet / Internal** selected. Internet access is a separate administrator grant; registration is not an Internet-approval request.
5. Choose **DSH workspace**, **Web Terminal** or **JupyterLab** in **Open after sign in**, then sign in.

An AD identity that conflicts with an existing local username is refused for administrator review. DSH does not automatically merge identities, replace passwords or assign another identity's history. Keep using the existing local sign-in until the administrator resolves ownership and preserves the required data. See [AD identity and collision rules](LDAP_AUTHENTICATION.md).

## 2 Work with chats and files

Select a project workspace and start a conversation. Describe a bounded task, identify the files to use and review the proposed changes and saved outputs. Keep durable work in the workspace location supplied by your operator.

Each provisioned user/environment has its own execution and storage boundary. Internet and No Internet environments have separate files, history, attachments and credential state. Shared model inference does not grant access to another user's files. Switching environment does not copy your conversation or project automatically.

Persistent files and settings can survive a worker replacement. Running processes and in-memory notebook variables require separate recovery; persistence is not a backup. Use the operator's backup and restoration process for deleted content.

## 3 Use the terminal, notebook and coding clients

Open **Web Terminal** or **JupyterLab** from your authenticated site. They execute with your assigned workspace identity and environment permissions. Terminal access does not grant administrator or cluster-management rights.

Use the installed managed entry points for Claude Code, Kilo Code or TrueForge where your operator has enabled them. Client configuration and supported features can differ; see [client compatibility](LIVE_CLIENT_COMPATIBILITY.md) and [managed-client validation](MANAGED_CLIENT_VALIDATION.md). DSH and these clients use the configured shared model route rather than a separate GPU copy per user.

Keep credentials out of prompts, shared files and reports. DSH sign-in does not create a Kerberos ticket or grant datalake permissions. Use the approved private authentication process for any separate data service.

## 4 Publish an application URL

Open **My applications**, select an available name, and register your application's port or an approved external HTTPS destination. A saved URL does not start a server, install DNS or enable Internet access.

Use **Require DSH sign-in** for private applications. Public access is an explicit choice for an approved mapping; it must not be used for protected data. An external application's own authentication remains separate from the DSH gateway session.

The administrator controls the per-user name limit, allowed domains, reserved names and available hostname/path routes. Opening Jupyter in Main DSH starts it when needed and reuses a running server and kernels. Internet approval and administrator service restrictions still apply. A worker restart ends in-memory kernels; saved notebooks remain in the private workspace. Other application restart requires an administrator-approved service configuration; unregistered processes are not automatically relaunched. See [application URLs, routing and restart controls](APP_PROXY.md).

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
