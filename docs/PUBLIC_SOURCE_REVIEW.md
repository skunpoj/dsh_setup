# Public-source review

This repository contains generic product source and examples. Site hostnames, registries, personal paths, credentials, private runtime receipts, user histories and coordination notes belong outside this repository.

Before publication, review the exact current tree and changes. The deterministic guard in scripts/scan_public.py detects common access-token forms, private-key markers, personal paths, credential-bearing URLs and organization host identifiers without printing matching values. It inspects ZIP-based Office document members and rejects unreadable or oversized archives for manual review. It does not examine Git history, video/audio content or the meaning of rendered documents. Passing it is not an absolute secrecy guarantee.

Two narrow existing fixtures are retained: the deliberately invalid renderer-test credential URL, only in its exact test path, and the digest-pinned vendored ttyd executable. All ten complete private keys embedded in that executable match public Mbed TLS v2.28.9 self-test fixtures; a changed executable loses the exception. Generic private address ranges in network blocklists and synthetic tests are not deployment addresses.

The publication review also checked the six platform screenshots visually: they show synthetic accounts/examples and no deployment hostname or secret. Compressed Office contents and readable PDF streams were pattern-scanned. Existing video frames/audio were not exhaustively reviewed. Historical commits are not rewritten by this change.

The managed-agent addition deliberately excludes local evidence, running image identifiers, cluster/resource identities and private handoff records. Its README distinguishes source tests from installation and runtime acceptance.

Run locally or in CI:

~~~sh
python3 -m unittest discover -s tests -p test_public_scan.py -v
python3 scripts/scan_public.py .
~~~

The Public source review workflow runs the guard and offline managed-agent policy tests; it has read-only repository permissions, no deployment credentials and no model-provider calls.
