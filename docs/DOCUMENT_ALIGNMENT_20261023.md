# Current guide alignment — 23 October 2026

The current 31-slide guide and its HTML/Markdown are generated from one source.
The current edition covers on-demand Jupyter, idempotent Start, explicit Restart,
Stop and enabled/disabled startup after workspace replacement. See
[Jupyter and application lifecycle](JUPYTER_APP_LIFECYCLE.html).

Two disposable users and four full Pod replacements verified twelve saved files
byte-identical. Explicit Restart ends running kernels; saved notebook content is
not live Python memory. This is not a restart test of live legacy accounts.

The capacity planner executes in the controller. The active Main gateway has
26 retained modules; its unused planner copy was removed. Source overlays and
the unchanged base runtime image must be checked separately.

Original Pilot and Routing decks and earlier videos remain historical evidence.
The captioned lifecycle video is an illustration of verified behavior, not a new
live-screen recording. Current guide links take precedence for these controls.
Latest GPU trial results retain their own qualification status; no near-1M or
compaction success is asserted by this document update.
