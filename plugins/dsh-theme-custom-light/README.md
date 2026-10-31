# Custom light theme for DSH (0.3.1)

A settings switch, "Custom light theme", directly under Appearance. DSH's own Appearance setting (Light, Dark, System) is left exactly as DSH ships it.

## What it does

- **Off (the default):** nothing changes. DSH shows its official logo and its native colours.
- **On:** while Appearance is Light (or System on a light device):
  - the colours come from a token layer over native Light;
  - the logo replaces DSH's own in the sidebar (`sidebar.brand.mark`, `sidebar.brand.name`) and above a new chat (`conversation.hero.brand.mark`). These are the slots the official brand plugin fills; this plugin registers at priority -10, and only while it is on and Light is active.
  - Dark, and any theme another plugin registers, are never changed.
- **Logo:** in order: the user's own image (a link starting with `https`, or an uploaded PNG, JPEG, GIF, WebP or SVG of 512 KB or less, stored as a data URL); then the deployment default at the same-origin path `/manual/brand/logo.png`, which the operator serves and the package does not bundle; then none.
  - **Collapsed panel and new-chat heading:** the image is cropped to a square from the left.
  - **Next to the mark:** the rest of a wide image is shown.
  - **Fallback:** an image that fails to load is skipped. With no loadable image the logo slots are not used, so DSH's official logo shows; the colours still apply.
- **Colours:** one field for each of the 32 palette tokens. Today's value is shown as the placeholder, and an empty field keeps it. Only `#hex`, `rgb()`/`rgba()` and `hsl()`/`hsla()` values are accepted.
- **Reset:** clears the logo and colours.
- **Storage:** everything is saved in the browser (`dsh-theme-custom-light/custom/v3`). A 0.1.0 "Custom" choice carries over once.

The package contains no artwork and names no organisation. To brand a deployment, serve your logo at the same-origin path `/manual/brand/logo.png`; users can also set their own image.

## Build and test

```sh
node build.mjs
node test/theme-service.mjs <path>/@deepseek-ai/dsh-client-ui-theme/lib/client.js
```

The test runs DSH's real `ThemeRuntime` from the runtime image (0.2.1-rc.5); slots, React and the settings transport are test doubles. Its 15 checks cover:
- the native row untouched, and nothing changed on install;
- Light, Dark and System, including the official logo returning in Dark and when off;
- the native preference never written;
- colour override, rejection of invalid values, and reset;
- logo validation: `https` and inline images only, with a size cap;
- the crop styles, and saved and migrated settings;
- foreign themes and token layers left alone;
- unload, and blocked storage;
- the settings row: the switch, the logo inputs and 32 colour fields, with neutral wording;
- a bundle with no network URLs and no organisation name.

Not covered: browser rendering, real image loading and cropping, and the real slot election.

## Install

```sh
dsh plugin --profile <your-profile> add ./plugins/dsh-theme-custom-light
```

The runtime image bakes this in, and `DSH_NATIVE_THEME_PLUGIN=1` installs it at start. The image's build check must expect the brand slots to be registered only while the theme is on.
