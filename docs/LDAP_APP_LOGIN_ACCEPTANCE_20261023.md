# LDAP application sign-in qualification - 23 October 2026

The application-login correction is committed, but the Production gateway has
**not yet been updated**. The course deployment owner confirmed that its full
build/deployment window remains open. The LDAP change must wait for that window
to close and for a fresh gateway source/configuration snapshot.

## Verification completed

An isolated gateway used the same runtime image and all 25 gateway source files,
with only the reviewed authentication modules changed. It authenticated against
the real corporate directory using the approved test principal. All **10 full
HTTP tests passed**, covering:

- Existing local recovery sign-in and visible AD/Local choices.
- Valid AD credentials with a matching manually created username: HTTP409 and
  the instruction to contact the administrator to delete the local account.
- Approved-domain UPN and domain-style identifiers reaching that same conflict
  check rather than failing prematurely in the application form.
- First AD sign-in producing an ordinary No Internet identity in the fixture.
- Successful application return for the canonical owner; denial of another
  owner, an unapproved domain, and a UPN submitted as a local account.
- Internet remaining unavailable until administrator approval.
- No local-password fallback for an AD account, and corporate AD password handling.
- Account identity and an authenticated session surviving fixture replacement.

The fixture had no production account, workspace or history mounts, no ingress
or service-account token, and only the required directory/DNS destinations.
Its five temporary Kubernetes resources were removed after saving the result.
The production directory configuration was retained.

Two read-only production captures checked **220 session/attachment files across
30 main execution workers**. All file hashes, lengths, worker identities,
restart counts and volume definitions matched. No files were missing, changed
or added between those captures. This confirms preservation during the isolated
qualification; it is **not post-rollout acceptance**.

Earlier source qualification also passed 33 LDAP/identity/gateway checks and a
68-test app-login, alias, HTTP/WebSocket access and LDAP regression selection.
The exact LF candidate was independently verified against its recorded hashes.

## Remaining release steps

1. Obtain explicit release of the entire course build and deployment window.
2. Recapture the current gateway source, image, configuration, accounts,
   sessions, application registry, manuals/course state and history hashes.
3. Review a fresh two-module source change while preserving the other modules,
   LDAP Secret, environment, image and storage mounts. Do not apply the old
   source snapshot merely because it passed earlier tests.
4. Replace the gateway only; retain the previous complete specification for a
   source-only rollback. Never restore older account or conversation data as
   part of an authentication rollback.
5. Verify actual live AD UPN/application login, local conflict behavior, local
   recovery, API/session behavior and history preservation after handover.

Until those steps complete, this result must be described as **real-AD isolated
qualification passed; Production deployment pending**. No current live
app-focused UPN acceptance is claimed from a main-page AD login or a local-app
login alone.

See [configuration and identity rules](LDAP_AUTHENTICATION.md).
