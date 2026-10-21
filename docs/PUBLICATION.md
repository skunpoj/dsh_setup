# Public publication boundary

This repository is a portable fresh-install reference and public learning
material. It is not a mirror of any live organization's infrastructure or an
operational evidence archive. Its example configuration must be adapted and
qualified before use. Presentation examples do not imply that every described
business workflow or control is implemented in this reference.

Keep deployment-specific source and evidence in a separate, access-controlled
repository. Never merge an old deployment branch or history into the public
repository. Use a fresh clone after a public-history replacement.

Before publishing:

1. Inspect source and configuration for real domains, network addresses, user
   identities, credentials, storage paths and private registry references.
2. Review documents, notes, metadata, hyperlinks and embedded media. Render and
   inspect presentation/PDF output. Pattern scans cannot inspect every image.
3. Run `python scripts/scan_public.py .` and
   `python scripts/check_public_release.py .`. Maintainers should also run the
   latter with a private local term list stored outside the repository.
4. Run the reference tests. Publish only reviewed artifacts and read back the
   public downloads. Test QR codes on rendered slides, not only their source PNG.

No scan can guarantee that previously downloaded, forked or cached copies have
disappeared. Historical pull-request refs and cached objects may require hosting
provider assistance after a history rewrite. Any real credential exposure also
requires revocation by its owner; removing a file does not revoke a credential.
