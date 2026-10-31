# Risk-first course delivery

Where a learning library is configured, the authenticated `/manual/course/` route provides English videos, captions, chapter navigation and accompanying source views. Begin with the [three risk controls](THREE_RISK_CONTROLS.md); keep feature lessons and worked examples separate from technical GPU setup and measured results.

Use the published contents list for available lessons. Do not hardcode chapter counts, image digests or module counts into everyday instructions. Each lesson identifies its source snapshot; it does not silently redefine the current deployment.

## Learner workflow

1. Sign in through the deployment's normal DSH route and open the course.
2. Choose a chapter, press Play and enable English captions.
3. Seek with section links and pause before trying commands in a private project.
4. Inspect the associated source view and use a reproduction package only for its intended synthetic examples.

A lesson or learning ZIP does not grant Internet access, another user's files, service credentials or dataset permissions. The normal environment and identity boundaries still apply.

## Publication architecture

Keep approved course assets on a separate read-only mount, outside user workspaces. Use a digest-pinned data image and a bounded manifest describing paths, sizes and hashes. Stage sanitized source views; never package live account files, private profiles, prompts, tickets or credentials.

The authenticated gateway checks the session and approved hostname before bounded file/media serving. Support valid HTTP byte ranges for seeking and reject invalid ranges. Keep course files immutable to execution users. Logout and disabled-account rules must apply to media routes as well as HTML pages.

## Controlled update procedure

1. Preserve the previous data image, manifests and current deployment specification.
2. Build the approved data image and read back its immutable digest, complete manifest and actual file bytes. Check the destination quota and inodes before activation.
3. Prepare a course-only patch against a fresh deployment specification. Preserve the complete current gateway source, authentication, routing, account/session mounts, manual root, package workflow and runtime image.
4. Refuse concurrent specification changes. Coordinate the gateway handover; do not restart user workers or the model to publish a video.
5. Verify the installed image identities and every manifest-bound file, then test authenticated playback, captions, seeking, downloads and sign-out denial.
6. Check existing users and durable history. Restore only the reviewed course fields on regression; preserve newer unrelated state and user writes.

The reference repository supplies gateway integration code. Operators supply approved learning assets, image repositories, registry authentication and site routing privately, then qualify their installation. See [installation](INSTALL.md), [acceptance](ACCEPTANCE.md), [publication boundaries](PUBLICATION.md) and [GPU setup](../gpu-stack/README.md).

## Slide companions

PowerPoint downloads from the manual were retired on 30 Oct 2026, together with the bounded slide download service and its `/manual/downloads/*.pptx` routes (see [SLIDE_DOWNLOADS.md](SLIDE_DOWNLOADS.md)). The HTML companion pages are now the delivery format. Keep original editions as dated HTML archives with their exact source hashes. Keep site-specific decks out of this repository.

Promote the current guide's description and content together as one atomic manual edition, and retain the prior edition for rollback. Slide publication does not establish that a matching video has been deployed. Publishing ordinary manual files must not restart active workspaces.

## One current guide

Use the [canonical guide and archive policy](CURRENT_GUIDE.md) for the shared PowerPoint, HTML and Markdown source, old download compatibility and publication checks. Keep one primary current guide per deployment; site-specific settings remain private.
