# DSH video course

Use the English course alongside the [three risk controls](DSH_PLATFORM_GUIDE.html) and [everyday user manual](DSH_USER_MANUAL.html). Start with the boundaries for network access, execution and data, and authorized results. Continue with the feature lessons and worked examples. LLM/GPU setup and measurements are technical references after these controls.

## Open and navigate

1. Open the DSH course using the site's normal sign-in. The course does not create another account or grant Internet permission.
2. Choose a chapter from the course index. Its contents list identifies the published lessons. Press Play and enable English captions.
3. Use the section links to seek, or pause before trying a command. Practice in your own private project and selected environment.
4. Open the accompanying source view to inspect the implementation explained by that lesson. A lesson's source snapshot is identified independently of the current live configuration.
5. Download the reproduction ZIP for its examples and setup material. It is a learning package, not a copy of users' files, histories or credentials, and it does not update an existing deployment.

Use the package guide, application URL guide and managed-client guide for current task instructions. The captioned course-navigation walkthrough explains the player. GPU-specific lessons are available from the GPU course.

## How the lessons map to the three controls

| Control | Lessons and practical habits |
|---|---|
| Prevent external leakage | Choose No Internet for protected work; keep Internet staging separate; transfer approved dependencies rather than protected workspaces |
| Prevent damage or excessive access | Work in the assigned non-root runtime, use scoped credentials and mounts, separate originals from writable results, and respect resource budgets |
| Keep results contained | Use authorized file, history, terminal and notebook routes; choose app audiences explicitly; keep private content separate from administrative access metadata |

Remote services retain their own permissions and network controls. The course explains these connected responsibilities without treating DSH sign-in or a mounted workspace as authorization to additional data.

## Protected course delivery

Course media uses a separate read-only mount. A digest-pinned data image supplies approved files; it does not replace the DSH runtime or shared model. The initializer checks the course manifest and content hashes before the gateway serves them.

The gateway checks the authenticated session and approved hostname for media access. Bounded file serving and HTTP byte ranges support playback and seeking. Signing out or disabling an account revokes access through these routes. Course directories are not writable user workspaces and do not expose another user's files.

## Operator setup and updates

Follow the course-routing setup for the initial deployment. Keep image repositories, registry credentials and site-specific settings private. Publish only approved learning assets and sanitized source views.

1. Save a fresh gateway deployment specification and current course references in a private operator directory.
2. Build the approved course data image and inspect its immutable digest, manifest, actual byte counts and destination quota. Retain the prior data image and references.
3. Prepare a narrow course-only change. Preserve the complete current gateway source inventory, authentication, routing, package workflow, manual volume, accounts and sessions. Do not apply an older full deployment fixture to publish a video.
4. Compare against the fresh specification and refuse a concurrent change. Coordinate the handover with the gateway owner; a data-image update may replace the gateway, but must not restart user workspaces or the GPU model.
5. Read back the installed image identities and every manifest-bound file. Verify actual authenticated playback, captions, section seeking, downloads, valid/invalid ranges and sign-out denial.
6. Verify account/session preservation and the existing manual root. If recovery is needed, restore only the reviewed course fields against a fresh specification, preserving newer unrelated state and user writes.

Current chapter counts and installed content come from the published course index and its manifest. Use operator release records for image identities and dated qualification details.

## Current DSH guide

Read the current guide. It combines risk controls, daily use, application access and operator guidance in English.

Video lessons retain their own source snapshots.

## English Fola video library

Google Fola narration, English captions and chapter navigation are available in the following courses.

## Code lessons

- DSH course: 71 source lessons with Google Fola narration.
- GPU course: 25 source lessons with Google Fola narration.
- [Jupyter walkthrough](JUPYTER_DSH2_DSH3_WALKTHROUGH.html) and [application-sharing walkthrough](AUTHENTICATED_APP_SHARING_WALKTHROUGH.html).

## Video library — Test

All normal DSH users can access these Test documents and videos using their existing DSH sign-in. No separate reviewer approval or documentation password is required. This library is hosted in Test and is separate from your Main workspace. Signed-out visitors must sign in.

- Full English application course: 15 chapters, including the Main/Test application-access explanation.
- DSH workshop: 18 narrated chapters from the 21 October workshop.
- Expanded DSH/GPU technical guide: 44 narrated chapters based on the 19 October technical guide. Its source slides retain that edition; the new narration uses Fola. Use the current GPU results for later runtime measurements.

All listed narrated editions include English captions and chapter navigation. Save notebook and project work through the workspace normally; watching a video grants no execution or data permissions.

## Everyday walkthroughs — Main

These nine pages contain eleven narrated clips. Test library references open these same current Main pages.

- Course navigation
- Private Python packages
- JupyterLab
- [Jupyter on DSH2 and DSH3](JUPYTER_DSH2_DSH3_WALKTHROUGH.html)
- Application restart settings
- [Application sharing](AUTHENTICATED_APP_SHARING_WALKTHROUGH.html)
- Administrator application controls
- Signup capacity
- Platform capacity and managed clients

