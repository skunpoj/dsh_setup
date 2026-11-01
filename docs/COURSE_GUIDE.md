# English video guides

The deployment provides a normal authenticated user manual and an English video library. Narration uses Google Gemini Fola, with English captions and chapter navigation. Your operator supplies the deployment addresses and publishes only the approved library.

1. Sign in to the deployed DSH site using the team login.
2. Open the user manual, then the video course guide at `/manual/COURSE_GUIDE.html`.
3. Choose the DSH or GPU code course, a Jupyter/application-sharing walkthrough, or an Test lesson.
4. Turn on English captions and use the chapter selector to seek to a topic. Source references open the code; they do not imply that every function has an individually narrated timestamp.

The reference library includes 71 DSH code lessons, 25 GPU code lessons, a 15-chapter application course, an 18-chapter workshop and a 44-chapter expanded technical guide. The operator may publish different approved selections. All normal DSH users can access these Test documents and videos using their existing DSH sign-in. No separate reviewer approval or documentation password is required. This library is hosted in Test and is separate from your Main workspace. Signed-out visitors must sign in.

The 44-chapter technical guide preserves its 19 October source edition. Consult the deployment's current GPU results for later measurements. Original source slides and previous recordings remain preserved; a new narration edition does not upgrade their runtime evidence.

## Current and historical editions

The default **Current** library must contain only lessons reviewed against the current source commit and the deployment edition named by the operator. A source match is not runtime acceptance; deployment provenance and affected behavior need separate verification.

Keep older lessons under **Historical** with their source edition and retained hashes. In particular, `DSH_Three_Risk_Controls_20261028.pptx` and videos derived from its 28 October content are historical: they describe earlier OpenShell, SGLang and DeepInfer qualification status and must not be presented as the current governed-harness design. Do not delete or overwrite those files when publishing a current replacement.

See [the narration standard](VIDEO_NARRATION_STANDARD.md) for source binding, voice reuse, caption verification and safe publication. Deployment-specific hostnames, private release URLs, credentials and source recordings are not included in this portable guide.

## Main walkthroughs

The reference Main manual has nine walkthrough pages with eleven narrated clips: course navigation, private Python packages, JupyterLab, Jupyter on the additional owner-only sites, application restart settings, application sharing, administrator application controls, signup capacity, and platform capacity and managed clients.

Open these pages through your deployed manual. Test-library references point to the same current Main walkthroughs rather than maintaining separate copies. Site-specific pages and recordings are supplied by the operator.

## Agent runtime and execution backend supplement

The next current-edition supplement distinguishes today's managed-client entry points from the reviewed, not-yet-deployed `/agent-tasks` source candidate for **DSH Python SDK**, **Claude Code** or **Deep Agents** with an independent execution backend. It explains Web DSH as the authenticated control surface and the Python SDK as a direct, checkpointed runtime with explicit pause/resume approval. Its reviewed source is [Agent runtime and execution backend](AGENT_RUNTIME_AND_EXECUTION_BACKENDS.html). A 60-second Fola script and aligned captions are prepared under `docs/videos/`; no MP4 or live-publication claim is made until narration, spoken-content verification and source/runtime acceptance are complete.
