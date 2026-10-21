# Reference package validation

The curated reference package was checked on 17 October 2026. These checks do not certify the existing public repository history or a fresh GPU deployment.

- An isolated no-push container build completed, including pinned package checks and installed DSH module checks. Build digest: `sha256:6449df6be51a5cae09050fb817f25b937bad892c10fbfab8bb47ec4907e56eee`. The image was not published to a registry. Later documentation and manifest-renderer edits are not a rebuild of this digest.
- Linux source checks passed 29 Python tests without skips. Node checks covered password storage, routing, workspace policy, managed inference and model catalog behavior.
- The scheduler overlay was checked against the pinned SGLang image, including rejecting changed patch targets and deferring a second long chunked prompt while permitting a fitting short prompt.
- Kubernetes strict server-side dry run accepted 47 rendered objects in an isolated test namespace. This does not prove volume provisioning, CNI enforcement or GPU inference on a new cluster.
- The curated directory passed a redacted Gitleaks scan. Public Git history requires separate review and cleanup.

Before real use, render operator-specific values, provision private Secrets, build and publish an immutable runtime image, and perform the acceptance procedure. No fresh near-million-token GPU test was performed for this reference distribution.
