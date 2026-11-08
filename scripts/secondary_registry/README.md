# Registry source package

See [installation, CI, acceptance and recovery](../../docs/SECONDARY_REGISTRY.md). This portable package has no operational credentials or automatic deployment.

## Main DSH runtime image build control

The site deployment pipeline builds and verifies the immutable DSH runtime image; it does not deploy it. Automatic runs honor CI skip markers in the triggering commit message. A manual recovery build can override a skip marker by selecting `forceRuntimeBuild: true` when queueing the pipeline. The override is accepted only when Azure reports `Build.Reason=Manual` and the selected source is `refs/heads/main`; its default is `false`, and it cannot override automatic CI skip behavior. The pipeline runs the guard regression tests before Docker operations. After a successful build, test the exact pushed digest on the Test node before any production rollout.
