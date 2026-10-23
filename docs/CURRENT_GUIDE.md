# One current DSH guide

Maintain one canonical current guide for a deployment. Its PowerPoint, HTML and Markdown must be generated from one reviewed content source and describe the same implementation. The current guide should explain the three risk controls first, followed by identity and environments, private files and client workflows, packages, application access and administration. Put operator setup, shared-routing compatibility, preservation and recovery in the final section.

Use deployment-relative entry paths such as `/manual/DSH_CURRENT_GUIDE.html` and `/manual/downloads/DSH_Current_Guide.pptx`. Configure the actual hostname privately. The documentation index, course guide and detailed user manual should lead to this same canonical entry. Check every guide's navigation graph, rather than duplicating independent current editions for each host.

State the guide's platform scope explicitly. Mirroring the same guide on another site does not synchronize that site's identities, permissions, storage or configuration. Independent sites retain their configured access and storage boundaries.

## Historical editions

Retain original Pilot and Routing files and companion HTML in a versioned archive with filenames, slide counts, source revisions, sizes and SHA-256 hashes. Preserve the old download URLs and exact deck bytes. Mark old companion pages as superseded and link to the canonical guide. Keep historical snapshots out of the primary current-guide navigation.

An optional topic extract must be generated from the canonical source and labelled as an extract. Do not maintain it as another competing current guide. A combined filename alone does not reconcile outdated claims, mixed-language terminology, duplicated sections or stale measurements.

## Publication and acceptance

1. Pin the implementation reference and inspect source and accepted runtime evidence. Treat measurements and Test results according to their original scope.
2. Compare the authored content with every exported slide and all HTML/Markdown sections. Render and visually inspect all final slides. Record the exact saved-file hash and distinguish compatible import/render from native Office execution.
3. Validate all new links and the navigation paths from existing guides. Preserve original archive hashes and the prior manifest.
4. Use the bounded attachment service described in [slide delivery](SLIDE_DOWNLOADS.md). Add only the approved canonical filename to the immutable manifest and exact ingress paths, retaining existing audience, TLS, network isolation and archived downloads.
5. Stage attachments before updating guide links. Publish the documentation edition atomically with source/hash guards; reconcile concurrent changes instead of overwriting them.
6. Verify actual served content on every deployment, a browser download of the canonical file, its saved bytes and its presentation opening. Compare execution-worker identities, restart counts and relevant preserved state before and after. Guide publication must not restart active workspaces.

Keep site-specific decks and application examples in the private deployment repository. This portable reference describes the publication contract without embedding private assets, account state or credentials. Video lessons retain their own source snapshots; updating a guide does not silently regenerate a video course.

## Current course content

The [portable current guide](current-guide/DSH_CURRENT_GUIDE.html), [Markdown guide](current-guide/DSH_CURRENT_GUIDE.md) and [96-chapter course notes](current-guide/DSH_COURSE_NOTES.html) are maintained together. The [content source](current-guide/DSH_CURRENT_GUIDE.source.json), [notes source](current-guide/DSH_COURSE_NOTES.json) and [file manifest](current-guide/SOURCE_MANIFEST.json) describe the same portable edition. Configure site addresses privately; the site-specific PowerPoint and download assets stay in the private deployment repository.
