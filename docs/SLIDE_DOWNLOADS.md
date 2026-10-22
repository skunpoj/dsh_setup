# PowerPoint companion downloads

Serve reviewed `.pptx` companions as ordinary HTTP attachments. The companion page links to `downloads/<filename>.pptx`, so the same relative link works beneath the site's `/manual/` path and in an exported local folder containing `downloads/`. Keep the filename, slide count and SHA-256 visible on the page.

## Read-only delivery

`scripts/slide_downloads.py` serves only the exact filenames and hosts in a mounted `manifest.json`. Each entry contains its byte count and SHA-256. The server checks both on every response, sends the PowerPoint MIME type and an attachment filename, and accepts only GET or HEAD. Unknown hosts, paths, query strings and traversal attempts fail; missing or altered files return an unavailable response. It has no directory listing, upload, execution or arbitrary file route.

Mount only the reviewed files, manifest and server source. Run a digest-pinned approved Python-capable image as non-root, with a read-only root filesystem, dropped capabilities, no privilege escalation and no service-account token. Set small CPU/memory requests and limits. Deny outbound traffic and allow inbound traffic only from the site's ingress controller.

Add Exact ingress paths for each `/manual/downloads/<filename>.pptx` on the approved existing hosts, preserving their TLS and audience. The reference manual pages are public documentation; the slide route contains only material approved for that same audience. A site with authenticated manuals must enforce the same authentication on attachments before enabling the route. Never use this service for private workspaces, histories or account files.

Use immutable ConfigMaps or an approved read-only data image for these small artifacts. When creating ConfigMaps, avoid duplicating binary data into a client-side apply annotation; use reviewed create/server-side operations within the API request limit. Stage files and service first, verify actual HTTP attachment bytes, then atomically update the companion links. Keep the prior manual edition for rollback. An independent service and exact ingress paths avoid restarting active DSH workspaces or changing their gateway route whitelist.

## Acceptance

Run `python tests/test_slide_downloads.py` for attachment headers, HEAD, host/path/query/method denials and integrity failure. Also verify deployed image, mounted source, manifest, network policy and exact ingress paths. For every approved current or archived deck on each site, use a browser to save the actual attachment, compare its hash and size, and open the saved presentation to check slide count and representative slides. Record browser-download success separately from archive parsing or application rendering. Compare existing workspace pod identities and restart counts before and after publication.
