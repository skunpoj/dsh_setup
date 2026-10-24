# Credential service operation

The deployment scripts create the credential services; they do not replace the application image or rebuild user runtimes. Review your current gateway source and routing before applying an overlay. The supplied gateway integration checks exact source anchors and refuses unexpected source changes.

1. On a protected Windows operator machine, install Python `cryptography` and configure `kubectl` for the intended cluster. Choose a new DPAPI custody path outside the checkout. Run `python scripts/deploy_credential_vault.py --custody <protected-new-path> --runtime-image <approved-image-at-sha256>`. It pins OpenBao, initializes persistent encrypted storage, seals recovery material outside Kubernetes and creates separate environment access tokens. Do not initialize an existing vault again.
2. Keep private profile JSON files outside Git. Review each host, allowed IP, path template, HTTP method, parameter schema, resource scope and returned field. Start with the fixed GitHub profile in the test fixture as a structural example; do not substitute a generic outbound proxy. No Internet profiles must use only approved internal addresses and the correct enterprise CA.
3. Run `python scripts/deploy_credential_brokers.py --image <approved-image-at-sha256> --profiles-off <private-json> --profiles-on <private-json>`. Use `--enterprise-ca-configmap <existing-ca-configmap>` where required. Source and configuration are immutable versioned ConfigMaps. Secret resources contain keys; do not export them into reports or commits.
4. Capture the live gateway source ConfigMap data privately and qualify it with the disposable canary script. Run the broker, identity, connector, LDAP and rollout regression tests. The connector test requires an ephemeral TLS fixture generated outside Git by `tests/create_credential_connector_fixture.py`.
5. Apply `scripts/rollout_credential_gateway.py --expected-source <qualified-live-source-json> --private-output <protected-evidence-directory>`. It preserves the running image and mounts. The template includes ingress-controller access to the web port as well as worker access to the credential tool port. External HTTPS form/session checks are required on success and rollback; localhost readiness alone is insufficient.
6. Install the public adapter from the authenticated Credentials page in each private runtime. It writes only code, public CA and service configuration under `/state/credential-tools`. Verify authorized aliases list correctly and unauthorized environments are denied. Existing worker processes need not restart.

## Restart and recovery

Use `python scripts/credential_vault_operator.py status --custody <protected-path>`. After a vault restart, credential operations deliberately fail closed until an operator runs the `unseal` action with the same protected custody. Never put an unseal key or root token into a worker, chat, source file or browser URL. Ordinary DSH login does not require an unsealed vault.

Use `snapshot-restore-test --custody <protected-path> --output <protected-backup-directory>` to save an encrypted snapshot and verify it in an isolated temporary volume. Keep the snapshot and recovery custody under your approved backup policy. The restore test removes its own clone, never reinitializes Production and checks the restored data. Certificate renewal, audit retention and independent off-host backup replication require your normal operational processes.

Gateway rollback removes only this integration's source/configuration additions. The corrected narrow web-ingress rule remains intentional: withdrawing the feature must not block the existing login route. Check the actual public login and authenticated workspace after any rollback. Preserve user account, history and workspace volumes.

## Reproduce acceptance

- `node --test tests/test_credential_broker.cjs tests/test_credential_identity.cjs`
- Generate the connector TLS fixture, set `DSH_CONNECTOR_TEST_TLS_DIR`, then run `node --test tests/test_credential_connector.cjs`.
- `node --test tests/test_ldap_gateway.cjs`
- `python tests/test_credential_rollout.py`
- Disposable cluster acceptance: `tests/credential_canary_live.cjs`, `tests/credential_ui_live.py` and `tests/credential_restart_live.py` use synthetic accounts and must not mount production account or project storage.

Provider authentication with a real user's token is a separate private acceptance step. Do not mark it verified from a synthetic TLS fixture. OAuth consent and automatic Kerberos acquisition require approved application/service references and are not implemented by these scripts.

### Why OAuth and Kerberos are separate

The deployed API-token/PAT form does not require an OAuth application. OAuth would add a provider-hosted sign-in/consent flow so users can connect an account without pasting a token. Its application registration identifies the permitted callback URL and scopes; provider registration and consent must be configured before implementing and qualifying that flow.

Kerberos is the user's datalake authentication, normally obtained with `kinit`. It is independent of a DSH login and of an API PAT. Existing per-user Kerberos workflows and AD permissions remain unchanged. A shared system account is not required for this feature. An automated user-ticket flow needs the existing realm/KDC client configuration, private input and cache location, and the intended renewal/expiry rules. Inspect the existing deployment or user configuration first; do not invent a realm, borrow another user's ticket or put passwords/keytabs into chat. These optional integrations are not prerequisites for using the deployed API-token form.
