# Reviewed DSH compatibility patch exports

These are reproducible review artifacts over official published npm module files, not a source fork and not a second runtime patch engine. `scripts/configure_models.js` remains the guarded application engine; environment-specific profile generation stays there. The exported diff uses the neutral `dsh.example.com` host and must not be manually applied to a running installation.

Each version directory includes an upstream/local target manifest, exact SHA-256 hashes, the configurator hash and a unified diff. CI refuses stale exports after configurator changes. The upstream input contract remains `scripts/upstream_patch_contract.json`; do not replace its hashes automatically to make a new upstream release pass.

To regenerate, obtain pristine targets from their official archives and independently verify published SHA-512 integrity and contract SHA-256. Copy that tree to an isolated writable candidate, run `configure_models.js` with `DSH_PACKAGE_DIR`, a disposable `DSH_HOME` and `DSH_TRUSTED_HOST=dsh.example.com`, then run:

```
python scripts/export_upstream_patchset.py --pristine ORIGINAL_TREE --patched CANDIDATE_TREE --output patches/dsh-0.2.0-rc.2
node tests/test_upstream_contract.js
```

A changed upstream package requires reviewing semantic differences and adapting tests before changing the contract. A matching diff or a passing build is not copied-state, browser, network or Production acceptance.
