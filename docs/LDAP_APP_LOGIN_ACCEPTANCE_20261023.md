# LDAP application sign-in acceptance - 23 October 2026

The main gateway application-login correction is deployed and verified. Both the
ordinary DSH login and an authenticated application login accept an AD user
principal name (UPN). The application flow canonicalizes an approved-domain
identifier before checking the registered application owner, then performs the
real directory authentication. Canonicalization does not grant access.

## User behavior

1. Select **AD / LDAP** and enter the approved AD identifier and password.
2. An ordinary account enters its private **No Internet** environment. Internet
   access remains subject to separate administrator approval.
3. An application-focused login returns only to its registered destination after
   the authenticated canonical identity passes its owner/access checks.
4. If an existing manually created account has the same canonical username, sign-in
   stops with HTTP 409 and asks the user to contact an administrator to delete the
   locally created account. No identity, password, file or history is automatically
   merged, deleted or reassigned. Administrators must preserve required data before
   resolving a collision; an error is not permission to erase it.

## Live deployment checks

Actual approved-domain UPN sign-in passed on the deployed main DSH route and the
registered application-focused route. The returned session matched the intended
user and No Internet environment; the application returned its actual HTML.
Both test sessions signed out successfully and subsequently received HTTP 401.
The ordinary AD account received HTTP 403 from the administration API. The
published manual also returned its HTML after the gateway restart. No model
question was submitted by these authentication checks.

After the course-only gateway update, the same actual UPN/main/application checks
passed again: the ordinary account remained in No Internet, administration was
denied, the manual and registered application returned their HTML, and both
owned test sessions signed out. Live readback retained the same application
image and all 25 accepted LDAP source files.

The rollout changed exactly **two authentication modules among 25 source files**.
The running application image, directory configuration, workspace mounts, course
and manual state were retained. Independent readback matched all 25 installed
source hashes and the intended deployment specification. All **13 existing
account records** and **five unexpired browser sessions** were preserved.

Fresh captures before and after the gateway replacement compared **220 history
and attachment files across 30 main execution workers**. Their hashes and lengths
were identical; worker identities, restart counts and volume definitions were
unchanged. This was a gateway-only replacement, not a worker restart test or an
inspection of every conversation's future tool behavior.

## Collision and regression checks

After deployment, an isolated gateway mounted the exact installed source and
used the same image and real corporate directory. All **nine scenarios passed**
(the test runner reports **10 passes**, counting their parent test as well):

- Local recovery login and visible AD/Local choices.
- Valid AD credentials colliding with a manual account: HTTP 409, the administrator
  instruction, no session and byte-identical fixture account data.
- Application-focused login displaying both providers and retaining its collision error.
- Approved-domain UPN and domain-style identifiers reaching the collision check.
- First AD sign-in creating an ordinary No Internet fixture identity.
- Application return for its canonical owner; denial of another owner, an
  unapproved domain and a UPN submitted through the Local provider.
- Internet access requiring administrator approval.
- No local-password fallback for an AD identity.
- Identity and session persistence across fixture process replacement.

The fixture never mounted production accounts, workspaces or histories. Its four
owned temporary resources were removed; the installed source and production
LDAP configuration were retained. Collision behavior is qualified by this
controlled real-directory fixture, not by altering an existing human account.
Earlier source checks passed 33 LDAP/identity/gateway cases and a 68-test
application/alias/HTTP/WebSocket/LDAP regression selection.

## Coordinated release and recovery

The course owner paused gateway activation and explicitly released a bounded
LDAP window while course builds continued. The fresh source/specification,
accounts, sessions, application registry, manual/course state and histories were
captured before applying the change. The course rollout was not declared
complete by this handover. Gateway ownership was returned with a fresh accepted
configuration so later course activation preserves the authentication fix.

The operator refuses conflicting source/specification or protected-state drift,
checks unknown mutation outcomes before retrying, and retains a reviewed
source-only recovery specification. Authentication rollback must never restore
older account or conversation data. Ten offline operator guard tests passed;
these are separate from the live login and persistence checks above.

See [LDAP configuration and identity rules](LDAP_AUTHENTICATION.md).

## Public application sign-in correction after restart

The subsequent gateway-only correction is deployed as generation 91. A public
application's focused sign-in URL returns directly to that registered public
application without creating a DSH session. Authenticated applications retain
their existing owner/access checks and AD/Local sign-in. Unknown, disabled or
invalid aliases do not become open redirects. This does not make a protected
application public or alter its saved access policy.

Independent real-directory checks after the replacement passed on both ordinary
DSH and authenticated application login. The canonical account entered No Internet,
received HTTP 403 from the administration API, and opened the actual application
and manual HTML. Both owned test sessions signed out and subsequently received
HTTP 401. These checks did not submit a model question or sign out another
person's browser session.

Readback matched all 25 intended mounted authentication/helper source files and
the retained application image. Thirteen account records, four existing unexpired
sessions, application routes/settings, manual and course state were preserved.
The rollout owner's comparison retained all 32 original execution workers.
An independent content capture additionally compared all 30 original main workers:
their identities, restart counts and volume definitions were unchanged, and all
220 existing history/attachment files (9,840,775 bytes) retained identical lengths
and SHA-256 hashes. A separately owned concurrent test worker was excluded from
the original-worker comparison; it was not removed or assigned to another user.
This verifies preservation across the gateway replacement, not a restart of every
user worker or resumption of every historical tool operation.

## Final authentication and preservation check on generation 92

After the subsequent source-only on-demand Jupyter gateway update, independent
readback matched all 27 intended mounted source files and the exact target
specification. Real AD/UPN login, authenticated application return, ordinary-user
admin denial, manual HTML and both owned-session logouts passed again. The
account remained in No Internet. DSH and GPU course indexes, reproduction ZIPs,
sampled chapter HTML/captions and video HEAD/range responses matched their
pinned content; protected course access was denied after logout.

A fresh independent capture again found all 30 original main workers unchanged
in identity, restart count and mounts. All 220 original history/attachment files
(9,840,775 bytes) retained their lengths and SHA-256 hashes. Additional synthetic
test files and the separately owned concurrent test worker were kept outside the
original-file comparison. No user worker was restarted by this gateway change,
and these checks did not submit model questions or restore persistent state.
