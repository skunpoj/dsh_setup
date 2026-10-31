# dsh-theme-custom-light

An optional DeepSeek Harness Web plugin that adds a **Custom Light** appearance beside the native Light, Dark and System themes. Native themes stay exactly as upstream DSH ships them; System continues to follow the device colour scheme. The plugin registers through the DSH theme service and the supported Appearance settings slot and does not modify built application assets.

Installation does not select Custom Light. Choosing it stores only a version marker, the selected state and the native fallback preference in browser-local storage, so the choice is per browser origin and profile, not synchronized between accounts or devices. Native choices keep their normal DSH settings transport. Removing the plugin restores the native Appearance row and preference.

## Structure

The layout follows [bugmaker2/dsh-plugin-template](https://github.com/bugmaker2/dsh-plugin-template), reduced to a client-only plugin with no runtime dependencies:

```text
package.json         # dsh.bundle + dsh.client manifests, scripts
cordis.patch.yml     # mounts the host row into a profile
dsh.plugin.json      # registry manifest
lib/index.js         # empty host entry (name/apply)
lib/client.js        # prebuilt Web client bundle (node build.mjs)
src/palette.mjs      # Custom Light token values
src/controller.mjs   # selection, fallback and persistence
src/client.mjs       # theme registration and Appearance slot
test/                # service tests against published DSH bundles
```

## Install

From a checkout containing this directory, into an explicitly selected profile:

```sh
dsh plugin --profile <your-profile> add ./plugins/dsh-theme-custom-light
```

Restart that profile through its normal deployment process. Remove it with `dsh plugin --profile <your-profile> remove dsh-theme-custom-light`. Managed deployments install it with `scripts/install_native_theme_profile.cjs`, which accepts only the qualified `lib/client.js` hash; see [NATIVE_THEME_INTEGRATION.md](../../docs/NATIVE_THEME_INTEGRATION.md).

## Development

Rebuild the client bundle with `node build.mjs`, then update `CLIENT_SHA` in `scripts/install_native_theme_profile.cjs`. To run the service tests, install the pinned development dependencies and run `npm test`; the tests use the published DSH 0.2.1-rc.2 theme and slot services, with React rendering, the Cordis facade and the settings transport as test doubles.

The palette carries 32 aliases from the gateway login stylesheet `scripts/platform.css`. Broad element selectors, hashed class selectors and global `!important` declarations are not copied, so this preserves the palette, not pixel parity. Palettes from the dshbase theme gallery can replace `src/palette.mjs` after review; the gallery's Skin Center, which writes body theme attributes directly, is not installed by this package.

## Qualification

The service tests and the named-profile lifecycle checks (discovery, activation, disposal, removal and rollback) do not establish browser rendering or deployed behaviour. Before promotion, qualify all four choices, refresh, font changes, OS scheme changes, removal, chats and attachments against the exact profile and image.

## License

MIT
