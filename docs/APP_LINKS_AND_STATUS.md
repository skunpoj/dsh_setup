# Applications, working links and deployment status

Use the Main DSH site for your private workspace and application settings. Main already provides local application ports, approved external HTTPS targets, authenticated access and Public mappings. RegChat is a configured example of those controls.

## Main services

| Open | Purpose |
| --- | --- |
| Main DSH | Team sign-in and your private workspace. |
| My applications | Configure an approved local port or external HTTPS target and its visitor access. |
| RegChat with DSH sign-in | Configured authenticated example. The mapping permits its approved DSH visitors. |
| RegChat Public alias | Configured Public example. Public skips the DSH gate for this mapping. |
| [User manual](DSH_USER_MANUAL.html) | Environments, tools, workspaces and administrator controls. |

Saving an address does not start an application or grant Internet access. Each destination keeps its own data permissions and can require a separate application login. JupyterLab, terminals and management routes remain owner-only. See [application sign-in and return](APP_SIGNIN_AND_RETURN.html) and [managed model login](MANAGED_PROVIDER_LOGIN.html).

## Test examples

| Open | Verified flow |
| --- | --- |
| Gated Test App5 | When signed out, open normal DSH sign-in in a new tab, sign in, then return to the original app tab. The tab resumes the original application and path. |
| Public Test App6 | Reach the application's own login without a DSH cookie. Its protected content still requires its application session. |

App5 and App6 are controlled Test fixtures. The fresh DSH logout/relogin check resumed App5 and restored normal No Internet DSH sign-in. That browser retained its separate destination session. A separate App6 check verified its own login without DSH and confirmed that its Public session could not bypass App5's gate.

The Main app-focused sign-in page and the Test continuation page are different interfaces. The Test flow resumes the original tab after normal sign-in. It does not automatically redirect the normal login tab to the app.

## Slides and English video

The updated full course and its media library are hosted in the dedicated Test documentation site under its existing reviewer permissions. Media hosting in Test does not mean Main's application controls are Test-only.

| Material | Open |
| --- | --- |
| Full English course, all previous chapters retained | Watch the full course |
| Main/Test status and app links | Watch the focused English update |
| Full course slides | Download the 48-slide PowerPoint |
| Application-routing slides | Download the 17-slide PowerPoint |
| Focused Main/Test update | Download the 3-slide PowerPoint |
| Detailed routing guide in the Test media library | Open the guide |

The separate Main overview guide and course-note library keep their existing addresses and content. This course update preserves those documents, existing users, histories and running workspaces.
