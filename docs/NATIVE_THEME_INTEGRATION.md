# Native DSH theme integration

The native application keeps original Light, Dark and System behaviour. The optional Custom Light palette is registered as Custom through the theme service. The gateway overlay version 3 styles the authentication page only; its transformation preserves the application renderer body and rejects unknown legacy wrappers.

The runtime package is dependency-free. A qualified immutable operator projection supplies the seven packaged plugin files under /opt/dsh/plugins/dsh-theme-custom-light, the profile installer under /opt/dsh/scripts, and the startup script from the same reviewed revision. Enable DSH_NATIVE_THEME_PLUGIN=1 only in that qualified deployment. This avoids modifying the served web assets and does not require an image rebuild for a managed profile/plugin release. The base application image identity and managed profile/artifact identity must both be recorded.

At startup the ordinary state seed and provider-default upgrade complete first. The opt-in installer then adds dsh-theme-custom-light to the web profile bundle inventory and materializes the exact prebuilt package under that profile. It does not use npm, fetch dependencies, read credentials or inspect session events. It preserves all other profile manifest fields, retains the original package.json bytes in .native-theme-rollback/<sha256>/web-package.json (or an absent marker), refuses symlinks/different pre-existing package contents, and checks for a concurrent manifest edit before the atomic replacement. It does not choose Custom or replace a native preference.

Installation requires explicit absolute state/package paths:

```sh
node scripts/install_native_theme_profile.cjs /absolute/state /absolute/qualified/dsh-theme-custom-light
```

This is a state-changing operation. In an actual deployment it belongs to the single release executor after a fresh state backup, exact current profile and workload identities, and a qualified Test run. Restore the saved manifest bytes (or its recorded absence), the previous immutable gateway/startup projection and the previous deployment specification for rollback; keep existing plugin files and history rather than deleting user state. Restart through the established release path and verify actual content.

Native browser acceptance must cover Light/Dark/System/Custom, page refresh, font changes, OS scheme changes in System, plugin removal/rollback, chats and attachments. Confirm that the native application response contains no forced platform-theme style. Preserve the login-page wrapper and confirm login/logout behaviour through the approved route. Record the exact plugin/source revision, artifact hashes, gateway/startup projection and running image digest. A host-entry boot, source tests or a succeeded CI badge alone is not deployment acceptance.
