# PowerPoint companion downloads (retired)

Retired on 30 Oct 2026, with the user's approval, during the shared-app cleanup. The operator deleted:
- the `dsh-slide-downloads` Deployment and Service;
- the `dsh-slide-downloads` Ingress (the `/manual/downloads/*.pptx` paths);
- its slide ConfigMap.

Backups are kept outside the repository. The service had 0 requests in the preceding 24 hours.

The manual no longer links to `.pptx` files. The HTML guide and the archived HTML companion pages are the delivery format.

To bring downloads back, restore the server (`scripts/slide_downloads.py`) and manifest (`k8s/dsh-slide-downloads.json`) from Git history before this note, together with their acceptance test, and re-add the page links in the same manual edition.