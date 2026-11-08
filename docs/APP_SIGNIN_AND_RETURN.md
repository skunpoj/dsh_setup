# Sign in to a published application

Open the application's registered address. DSH applies the access setting saved for that application. A name such as RegChat is an example of a configured application, not a special login mechanism.

## Choose the correct login

| What you see | What to do |
| --- | --- |
| A DSH sign-in page naming the requested app | Use your normal DSH identity. The gateway checks your access to that mapping and returns you to that application. |
| **Continue with your normal DSH login** | Select **Open normal DSH sign-in**, sign in in the new tab, then return to the original application tab. |
| The destination application's own sign-in page | Use the account accepted by that application. Your DSH identity is not automatically its application account. |

The normal DSH gateway supports app-focused sign-in. The separate Test gateway's continuation flow is described below; it is not an automatic cross-tab sign-in callback.

## Continue from normal DSH sign-in

1. Keep the original application tab open. It retains the requested application and path.
2. Select **Open normal DSH sign-in**. There is no separate Test password.
3. Sign in with the DSH account authorized for the application and select its configured environment.
4. Return to the original application tab. When it becomes visible, it checks the session and resumes the same application. If needed, select **I have signed in — continue**. The visible tab also checks periodically.
5. If the destination app has its own login, complete that separately. Passing DSH authentication does not bypass the destination's permissions.

If access is still denied, check the selected account, environment and mapping permissions with the owner or administrator. Do not change the address to an unrelated destination or enter a DSH password into a destination app merely because it is hosted behind DSH.

## Public access

**Public** skips the DSH sign-in gate for the specific approved application mapping. A visitor can reach that destination while signed out of DSH. The app can still require its own login, and its data permissions and write actions still apply. Public access does not open a DSH workspace, notebook, terminal, chat history or administrator page.

An owner must deliberately select Public for an appropriate application. Authenticated sharing is a different setting: it admits only enabled DSH accounts authorized by the mapping. JupyterLab, terminals and management services remain owner-only. See [sharing and isolation](AUTHENTICATED_APP_SHARING.html).

## Credentials and session boundaries

The gateway removes DSH authentication cookies and bearer credentials before forwarding requests to the app. Application cookies and the app's own session remain separate. Signing out of DSH ends its gateway access; it is not a universal sign-out command for every destination application's session. SSO requires a separately configured identity integration.

The alias and saved mapping determine the destination. An unknown or disabled mapping is not a valid gated sign-in target. Changing a mapping or its access policy requires the authorized owner or administrator; completing sign-in does not grant additional workspace or data permissions.

## Test examples

App5 is the gated Test example. A fresh signed-out browser must encounter the DSH continuation page, sign in through normal DSH, return to App5, and complete any application-specific login before seeing protected content.

App6 is the Public Test example. A signed-out DSH browser reaches its application login directly. Public describes the absence of the DSH gate; it does not mean the destination has no authentication.

These examples qualify the recorded Test paths. They do not change the access policy of another app or deploy the Test adapter to every site. RegChat remains a separate example mapping. See the [user manual](DSH_USER_MANUAL.html) for account, environment and application controls.
