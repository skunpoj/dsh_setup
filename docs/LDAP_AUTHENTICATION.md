# AD / LDAP sign-in

DSH supports verified LDAPS authentication alongside existing local accounts.
Choose **AD / LDAP** or **Local DSH account** on the sign-in page. The same choice
is available when signing in to a protected application URL.

AD verifies the password. DSH stores the canonical account name, immutable AD
object identifier and its existing workspace/Internet permissions. It does not
store the AD password, put it in a worker, or create a Kerberos ticket.

## Existing local username

After valid AD authentication, an existing local account with the same username
causes HTTP **409**, `LDAP_LOCAL_ACCOUNT_CONFLICT`:

> An existing locally created DSH account uses this AD username. Contact an
> administrator to delete the locally created account before signing in with AD.
> No account, files or history have been changed.

Names are case-insensitive. A bare username, an approved-domain UPN and an
approved-domain `DOMAIN\username` resolve to the same canonical identity. DSH
does not silently link accounts, replace local credentials or assign the local
workspace to the AD identity. The existing local sign-in remains available.

Application-specific sign-in must use that same configured-domain normalizer
before comparing an app's owner. UPN and domain-style forms must reach the
normal AD credential and local-account collision checks. Canonicalization alone
never authenticates a user or grants access to another user's private app.

The administrator must confirm ownership and preserve the account's storage and
runtime reservation before deleting its local sign-in record. Disabling an
account is not deletion. Do not delete workspace/history volumes or free an
assigned runtime slot as a shortcut. This feature never deletes an existing
account automatically.

## New AD users and Internet approval

Where automatic provisioning is installed, the first valid AD sign-in uses the
ordinary private-workspace capacity and admission checks. It creates a **No
Internet** account. Existing warm spare/replenishment behavior is unchanged.
For a static installation, provision the identity's private runtime targets first.

Internet remains disabled until an administrator uses **Allow Internet** in the
central Users dashboard. The dashboard shows whether the account uses AD / LDAP
or local sign-in. Disabling the account, signing out its sessions and revoking
Internet continue to use the existing administrative controls.

Directory group roles from another application are not copied into DSH. AD
accounts are ordinary DSH users; the configured local administrator remains the
recovery identity. A changed AD object identifier cannot acquire an existing
LDAP account's workspace. AD passwords must be changed through the corporate
directory rather than DSH's local password form.

## Configure an installation

1. Build a runtime containing the LDAP helpers and the pinned MIT-licensed
   `ldapts` client. The Dockerfile verifies its digest and runs synthetic identity
   and full-gateway tests. No package is downloaded when the gateway starts.
2. Keep a local administrator. For a fresh static installation, list runtime
   identities in `users`, and list the AD identities in `ldap_users` in the private
   installation YAML. `bootstrap_secrets.py` skips creating local passwords for
   those AD identities. Do not rerun bootstrap against an existing account store.
3. Obtain the approved directory root/intermediate CA bundle from a trusted
   certificate store. Create private files `config.json`, `bind-password` and
   `ca.pem` outside Git. Use this configuration shape with your own values:

   ```json
   {
     "version": 1,
     "domain": "example.com",
     "urls": ["ldaps://directory.example.com:636"],
     "bindDN": "directory-reader@example.com",
     "bindPasswordFile": "/ldap/bind-password",
     "caFile": "/ldap/ca.pem",
     "timeoutMs": 5000,
     "searchBases": ["DC=example,DC=com"],
     "searchFilter": "(sAMAccountName=%s)",
     "allowSignUp": true
   }
   ```

   `allowSignUp` controls first-time AD account creation. Existing accounts still
   require successful directory authentication on each new sign-in.

4. Permit only the approved controller addresses on TCP **636** from the
   **gateway** workload. Add exact controller names to its existing internal DNS
   allowlist while preserving existing entries. Do not enable public egress or
   grant directory access to ordinary execution workers for this feature.
5. Create a gateway-only Secret without printing its values:

   ```sh
   kubectl -n YOUR_NAMESPACE create secret generic directory-auth \
     --from-file=config.json=/private/directory/config.json \
     --from-file=bind-password=/private/directory/bind-password \
     --from-file=ca.pem=/private/directory/ca.pem
   kubectl -n YOUR_NAMESPACE patch deployment YOUR_GATEWAY \
     --type=strategic --patch-file k8s/ldap-gateway.patch.example.yaml \
     --dry-run=server -o name
   kubectl -n YOUR_NAMESPACE patch deployment YOUR_GATEWAY \
     --type=strategic --patch-file k8s/ldap-gateway.patch.example.yaml
   kubectl -n YOUR_NAMESPACE rollout status deployment/YOUR_GATEWAY
   ```

   The read-only Secret belongs only in the trusted authentication container,
   never in user workspaces, notebook containers, reports or public Git. No
   other mounts or deployment settings need to change.

6. Check actual sign-in, not only readiness: local recovery login; valid AD
   login; canonical-name collision; new-user No Internet default; admin approval
   and revocation; persisted account/identity and browser session after gateway
   replacement. Preserve users, runtime mappings, application registry, session
   storage and manual volumes during the handover.

## Connection and failure behavior

Only LDAPS on port 636 is accepted. Certificate-chain and hostname verification
are mandatory, with TLS 1.2 or newer. A source configuration that disables TLS
verification is not carried forward. There is no plaintext LDAP fallback.

The gateway binds the read-only search identity, performs an escaped and bounded
username search, and then binds the returned user DN with the submitted password.
Missing, ambiguous, disabled and changed identities are denied. Referrals are
not followed. A wrong password does not fan out to other controllers. Network
failover uses only the explicitly configured LDAPS endpoints, with bounded
timeouts and concurrent attempts. AD failure never falls back to a local
password.

Existing local browser-session stamps retain their format. New AD sessions bind
the account's directory object identifier to the protected session store. Gateway
replacement does not itself change local passwords or move user files/history.

## Tests and dependency maintenance

```sh
node --test tests/test_ldap_auth.cjs tests/test_identity_auth.cjs tests/test_ldap_gateway.cjs
```

The default tests use a synthetic directory and disposable local stores. The
gateway test optionally accepts `DSH_LDAP_TEST_CREDENTIAL_FILE` referencing a
private JSON file containing `username`, `password`, `domain` and `configFile`;
this explicit operator mode authenticates a real test principal while keeping
all DSH account changes in an isolated fixture. Never commit that file or use a
human account store as the fixture.

The client version, upstream package and digest are recorded in
[`vendor/ldapts/PROVENANCE.json`](../vendor/ldapts/PROVENANCE.json); its MIT license
is included. Review and retest the pinned dependency before updating it.

For the dated application-login correction and the distinction between isolated
qualification and Production rollout, see the
[23 October acceptance record](LDAP_APP_LOGIN_ACCEPTANCE_20261023.md).
