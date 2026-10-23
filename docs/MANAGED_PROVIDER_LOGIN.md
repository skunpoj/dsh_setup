# Team login and managed model access

Sign in once at your team's DSH login page. Use the configured local account or AD / LDAP option. The gateway opens your assigned private workspace in the selected environment. Internet approval and application access remain controlled by the administrator.

## No second DeepSeek sign-in

Managed LiteLLM profiles hide the official DeepSeek account page and its sign-in dialog. The approved model connection is already configured. You do not need a personal DeepSeek Platform account, external provider password or personal API key to use that connection.

The team login and provider login serve different purposes:

| Layer | Responsibility |
| --- | --- |
| Team gateway login | Identifies the person and selects the authorized private runtime and environment. |
| Native DSH Host authentication | Protects browser/RPC access to that runtime. The gateway establishes the authenticated upstream connection. |
| Managed LiteLLM connection | Authenticates model requests to the approved inference service using the configured deployment credential. |

An official DeepSeek account connects a model-provider account; it does not create private workspaces or replace the team's authorization. Profiles that deliberately use an external provider keep their upstream account interface.

## Everyday use

1. Open the team login page and select the environment and application.
2. Sign in with your team identity and open a workspace or conversation.
3. Send your request using the configured model. No additional provider sign-in is required.
4. Use **Logout** to end your team session. This does not delete files or history.

An already-open tab may retain the old account dialog. Preserve any unsent draft, close the dialog and refresh the page to load the current interface. If the team session expired, use the team's **Sign in again** link rather than the official provider sign-in dialog.

## Operator configuration

The managed profile uses the upstream plugin configuration, without modifying its callback validator, Host/Origin checks, native authentication, account grants or credential files:

```yaml
- id: ui-settings-account
  disabled: true
```

Apply this override only when the selected provider is the managed LiteLLM provider. `scripts/configure_managed_signin.cjs` validates that selection, preserves unrelated profile settings, retains original profile bytes for rollback and writes atomically. An explicit managed-transport marker also supports profiles that inherit the managed default from their bundle. An explicitly selected external provider remains unchanged.

Run the helper inside the intended runtime with its actual state home:

```sh
node /opt/dsh/scripts/configure_managed_signin.cjs "$DSH_HOME"
```

For an installed image that predates the helper, stage the reviewed helper through the operator's deployment process before running it. DSH profile hot reload applies the plugin change without restarting the worker. Verify the browser's active plugin registry, team login/logout and an actual persisted model reply. Preserve running worker identities, notebook processes and existing histories. If hot reload fails, retain the previous profile and investigate rather than restarting an active workspace automatically.

Image seeds and the workspace bootstrap apply the same policy for newly provisioned managed runtimes. Already running profiles retain the override in durable state across ordinary worker replacement.

See the [user manual](DSH_USER_MANUAL.html) for environments, tools, applications and administrator controls.
