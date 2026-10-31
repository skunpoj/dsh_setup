// DSH 0.2.1-rc.5: public theme API only (getTheme, overrideTokens, theme/change). No DOM or credential access.
// The custom light theme is a token layer over native Light, not a theme of its own: the native
// Appearance choices (Light, Dark, System) stay exactly as DSH ships them.
export const LAYER_ID = 'dsh-theme-custom-light';
export const STORAGE_KEY = 'dsh-theme-custom-light/custom/v3';
export const LEGACY_KEYS = ['dsh-theme-custom-light/light/v2', 'dsh-theme-custom-light/selection/v1'];
export const MAX_LOGO_CHARS = 700000; // about a 512 KB image as a data URL
// Served by the deployment, not bundled: the operator places the image at this same-origin path.
export const DEFAULT_LOGO = '/manual/brand/logo.png';
const COLOR = /^(#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})|(?:rgb|rgba|hsl|hsla)\(\s*[-0-9.%,\s/]+\))$/i;
const DATA_IMAGE = /^data:image\/(?:png|jpeg|gif|webp|svg\+xml);base64,[A-Za-z0-9+/]+=*$/;

// Only https: links and inline images; anything else is ignored and the default logo is used.
export function validLogo(value) {
  if (typeof value !== 'string' || value === '' || value.length > MAX_LOGO_CHARS) return false;
  if (DATA_IMAGE.test(value)) return true;
  try { return new URL(value).protocol === 'https:'; } catch { return false; }
}
export function validColor(value) { return typeof value === 'string' && COLOR.test(value.trim()); }

export function createCustomTheme({theme, tokens, onThemeChange, storage}) {
  let disposed = false, persistenceError = !storage, layerOff = null, applying = false;
  let enabled = false, logo = '', colors = {};
  const broken = new Set(); // logo sources that failed to load in this page
  const read = key => JSON.parse(storage?.getItem(key) || 'null');
  try {
    const value = read(STORAGE_KEY);
    if (value?.version === 3) {
      enabled = value.enabled === true;
      if (validLogo(value.logo)) logo = value.logo;
      for (const [name, color] of Object.entries(value.colors || {}))
        if (name in tokens && validColor(color)) colors[name] = color.trim();
    } else {
      // 0.2.0 kept only the switch, 0.1.0 a "Custom" choice; carry either over once.
      const v2 = read(LEGACY_KEYS[0]), v1 = read(LEGACY_KEYS[1]);
      if (v2?.version === 2 && typeof v2.enabled === 'boolean') enabled = v2.enabled;
      else if (v1?.version === 1 && v1.custom === true) enabled = true;
    }
  } catch { persistenceError = true; }
  const listeners = new Set();
  const notify = () => { for (const listener of [...listeners]) listener(); };
  const persist = () => {
    try { storage?.setItem(STORAGE_KEY, JSON.stringify({version: 3, enabled, logo, colors})); }
    catch { persistenceError = true; }
  };
  const layer = () => Object.fromEntries(Object.entries(tokens).map(([name, value]) => {
    const v = colors[name] ?? value; return [name, {light: v, dark: v}];
  }));
  // Only over the built-in Light theme: Dark, and any theme another plugin registers, stay untouched.
  const lightActive = () => theme.getTheme().active.id === 'light';
  const wanted = () => enabled && !disposed && lightActive();
  // The user's own logo first, then the deployment's; with neither loadable, DSH's official logo stays.
  const effectiveLogo = () => (logo && !broken.has(logo)) ? logo : (!broken.has(DEFAULT_LOGO) ? DEFAULT_LOGO : '');
  const sync = (force = false) => {
    // overrideTokens emits theme/change synchronously; the guard stops that echo re-entering.
    if (applying) return;
    applying = true;
    try {
      if (layerOff && (force || !wanted())) { const remove = layerOff; layerOff = null; remove(); }
      if (wanted() && !layerOff) layerOff = theme.overrideTokens(LAYER_ID, layer());
    } finally { applying = false; }
  };
  const off = onThemeChange(() => { sync(); notify(); });
  sync();
  const guard = () => { if (disposed) throw new Error('custom theme controller is disposed'); };
  return {
    getSnapshot: () => ({enabled, logo, effectiveLogo: effectiveLogo(), colors: {...colors}, applied: layerOff !== null,
      brandActive: enabled && !disposed && lightActive() && effectiveLogo() !== '', colorScheme: theme.getTheme().active.colorScheme, persistenceError}),
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    setEnabled(next) {
      guard(); if (typeof next !== 'boolean') throw new Error('enabled must be true or false');
      enabled = next; persist(); sync(); notify();
    },
    // Returns false (and keeps the previous value) for anything but an https: link or an inline image.
    setLogo(value) {
      guard(); const next = typeof value === 'string' ? value.trim() : '';
      if (next !== '' && !validLogo(next)) return false;
      logo = next; broken.delete(next); persist(); notify(); return true;
    },
    // An empty value restores the default; an invalid colour is rejected and the default stays.
    setColor(name, value) {
      guard(); if (!(name in tokens)) throw new Error('unknown colour token');
      const next = typeof value === 'string' ? value.trim() : '';
      if (next === '') delete colors[name];
      else if (validColor(next)) colors[name] = next;
      else return false;
      persist(); sync(true); notify(); return true;
    },
    // Called by the logo image's onError: that source is skipped for the rest of this page.
    markBroken(src) { if (typeof src === 'string' && src && !broken.has(src)) { broken.add(src); notify(); } },
    reset() { guard(); logo = ''; colors = {}; persist(); sync(true); notify(); },
    dispose() {
      if (disposed) return;
      disposed = true; off(); listeners.clear();
      if (layerOff) { const remove = layerOff; layerOff = null; remove(); }
    }
  };
}
