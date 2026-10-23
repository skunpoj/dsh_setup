# Applications, links and Main versus Test

Use the operator-approved Main DSH address for workspaces and application settings. The deployment supports local application ports and approved external HTTPS targets. Each saved mapping chooses authenticated or Public visitor access. RegChat is an example mapping rather than a hardcoded login mechanism.

## Main and Test roles

| Surface | Role |
| --- | --- |
| Main workspace and application settings | Daily workspace access and application configuration. |
| Main gated and Public example aliases | Configured application mappings with their own visitor policies. |
| Test App5 | Gated fixture for normal DSH sign-in and return to the original application tab. |
| Test App6 | Public fixture whose separate application login works without a DSH cookie. |
| Private Test media library | Hosts the deployment's full course and private slides under existing reviewer access. |

The reference deployment has the Main controls above. The recorded App5/App6 qualification belongs to Test. Test-hosted media does not imply that Main application controls are Test-only. Supply actual deployment addresses through your operator's private guide.

## Application login

An app-focused DSH sign-in page verifies your team identity and mapping access. In the Test continuation flow, keep the original app tab open, use its normal DSH sign-in link, sign in in the new tab, then return to the original tab. It checks the session and resumes the requested application. This is original-tab resumption rather than a same-tab callback.

Public skips only the DSH gate for its explicit mapping. The destination can still require its own account and enforce data permissions. DSH credentials must not be forwarded to that destination. A Public app session must not bypass an authenticated mapping. See [sign-in and return](APP_SIGNIN_AND_RETURN.html).

## Sanitized slides and English video

These materials omit private site addresses, user inventories, screenshots and credentials. The full private course remains in the deployment's protected documentation library. Configure site-specific links before distributing a deployment copy.

- [Download the focused PowerPoint](presentations/APP_LOGIN_MAIN_TEST_EN.pptx).
- [Watch the focused English update](media/APP_LOGIN_MAIN_TEST_EN.html).
- [Read the user manual](DSH_USER_MANUAL.html).
- [Read sharing and isolation controls](AUTHENTICATED_APP_SHARING.html).

The earlier full-course chapters, the separate Main overview guide and the course-note library remain available in the private deployment. Publishing this documentation does not change user accounts, private histories or active workspaces.
