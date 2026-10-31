window.__ModuleLoader__.load({id:"dsh-theme-custom-light",factory:(require)=>{const React=require("react");
// Default light palette (32 DSH alias tokens); every value can be overridden in the settings row.
const CUSTOM_LIGHT_TOKENS = Object.freeze({
  "--dsw-alias-bg-base": "#f4f7fa",
  "--dsw-alias-bg-layer-1": "#fff",
  "--dsw-alias-bg-layer-2": "#edf3f8",
  "--dsw-alias-bg-layer-3": "#e3ecf4",
  "--dsw-alias-bg-module-platform": "#edf3f8",
  "--dsw-alias-bg-multi-select": "#e3ecf4",
  "--dsw-alias-bg-document-preview": "#fff",
  "--dsw-alias-bg-overlay": "#e3ecf4",
  "--dsw-alias-label-primary": "#172b43",
  "--dsw-alias-label-primary-bluish": "#172b43",
  "--dsw-alias-label-primary-dimmed": "#29425e",
  "--dsw-alias-label-secondary": "#3e566f",
  "--dsw-alias-label-tertiary": "#52657a",
  "--dsw-alias-label-caption": "#52657a",
  "--dsw-alias-label-dimmed": "#64758a",
  "--dsw-alias-label-document-preview": "#172b43",
  "--dsw-alias-label-primary-foreground": "#fff",
  "--dsw-alias-label-primary-inverted": "#fff",
  "--dsw-alias-button-primary-fill": "#003366",
  "--dsw-alias-button-primary-hover": "#005a9c",
  "--dsw-alias-button-primary-dimmed": "#cbd7e3",
  "--dsw-alias-button-elevated-fill": "#edf3f8",
  "--dsw-alias-button-floating-fill": "#fff",
  "--dsw-alias-button-floating-hover": "#e3ecf4",
  "--dsw-alias-button-ghost-active-fill": "#dbe7f1",
  "--dsw-alias-button-ghost-active-hover": "#cbd7e3",
  "--dsw-alias-button-ghost-active-border": "#8da5bc",
  "--dsw-alias-border-l1": "#dce5ee",
  "--dsw-alias-border-l2": "#cbd7e3",
  "--dsw-alias-border-l2-darkmode-thin": "#cbd7e3",
  "--dsw-alias-border-l3": "#b9cadb",
  "--dsw-alias-border-l4": "#a4b9ce"
});

// DSH 0.2.1-rc.5: public theme API only (getTheme, overrideTokens, theme/change). No DOM or credential access.
// The custom light theme is a token layer over native Light, not a theme of its own: the native
// Appearance choices (Light, Dark, System) stay exactly as DSH ships them.
const LAYER_ID = 'dsh-theme-custom-light';
const STORAGE_KEY = 'dsh-theme-custom-light/custom/v3';
const LEGACY_KEYS = ['dsh-theme-custom-light/light/v2', 'dsh-theme-custom-light/selection/v1'];
const MAX_LOGO_CHARS = 700000; // about a 512 KB image as a data URL
// Served by the deployment, not bundled: the operator places the image at this same-origin path.
const DEFAULT_LOGO = '/manual/brand/logo.png';
const COLOR = /^(#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})|(?:rgb|rgba|hsl|hsla)\(\s*[-0-9.%,\s/]+\))$/i;
const DATA_IMAGE = /^data:image\/(?:png|jpeg|gif|webp|svg\+xml);base64,[A-Za-z0-9+/]+=*$/;

// Only https: links and inline images; anything else is ignored and the default logo is used.
function validLogo(value) {
  if (typeof value !== 'string' || value === '' || value.length > MAX_LOGO_CHARS) return false;
  if (DATA_IMAGE.test(value)) return true;
  try { return new URL(value).protocol === 'https:'; } catch { return false; }
}
function validColor(value) { return typeof value === 'string' && COLOR.test(value.trim()); }

function createCustomTheme({theme, tokens, onThemeChange, storage}) {
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

const inject = ['theme', 'slots'];
const h = React.createElement;
const MAX_UPLOAD_BYTES = 512 * 1024;
const BRAND_SLOTS = ['sidebar.brand.mark', 'sidebar.brand.name', 'conversation.hero.brand.mark'];
function useSnapshot(controller) {
  const [snapshot, setSnapshot] = React.useState(() => controller.getSnapshot());
  React.useEffect(() => {
    const sync = () => setSnapshot(controller.getSnapshot());
    const off = controller.subscribe(sync); sync(); return off;
  }, [controller]);
  return snapshot;
}
const muted = {color:'var(--dsw-alias-label-tertiary)'};
const field = {font:'inherit', padding:'0.25rem 0.4rem', border:'1px solid var(--dsw-alias-border-l2)', borderRadius:'4px',
  background:'var(--dsw-alias-bg-layer-1)', color:'var(--dsw-alias-label-primary)', minWidth:0};
// Its own row under Appearance: the native Light/Dark/System row is left as DSH ships it.
function CustomThemeRow({controller}) {
  const snapshot = useSnapshot(controller);
  const [message, setMessage] = React.useState('');
  const commitLogo = value => setMessage(controller.setLogo(value) ? '' : 'Use an image link that starts with https, or upload an image.');
  const upload = event => {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    if (!/^image\/(png|jpeg|gif|webp|svg\+xml)$/.test(file.type) || file.size > MAX_UPLOAD_BYTES) {
      setMessage('Choose a PNG, JPEG, GIF, WebP or SVG image of 512 KB or less.'); return;
    }
    const reader = new FileReader();
    reader.onload = () => commitLogo(String(reader.result));
    reader.readAsDataURL(file);
  };
  const uploaded = snapshot.logo.startsWith('data:');
  return h('div', {style:{display:'grid', gap:'0.4rem', paddingBlock:'0.5rem'}},
    h('label', {style:{display:'flex', alignItems:'center', justifyContent:'space-between', gap:'1rem'}},
      h('span', null, 'Custom light theme'),
      h('input', {type:'checkbox', role:'switch', 'aria-label':'Custom light theme', checked:snapshot.enabled,
        onChange:event => controller.setEnabled(event.target.checked)})),
    h('small', {style:muted},
      'When on, your logo and colours are used whenever Appearance is Light, or System on a light device. Dark is unchanged. Saved in this browser only.'),
    snapshot.enabled ? h('div', {style:{display:'grid', gap:'0.4rem'}},
      h('label', {style:{display:'grid', gap:'0.2rem'}},
        h('span', null, 'Logo image link'),
        h('input', {type:'url', style:field, placeholder:'Image link starting with https (empty = default logo)', 'aria-label':'Logo image link',
          key:'logo-' + (uploaded ? 'uploaded' : snapshot.logo), defaultValue:uploaded ? '' : snapshot.logo,
          onBlur:event => commitLogo(event.target.value),
          onKeyDown:event => { if (event.key === 'Enter') commitLogo(event.target.value); }})),
      h('div', {style:{display:'flex', flexWrap:'wrap', gap:'0.5rem', alignItems:'center'}},
        h('label', null, h('span', {style:muted}, 'Or upload an image: '),
          h('input', {type:'file', accept:'image/png,image/jpeg,image/gif,image/webp,image/svg+xml', 'aria-label':'Upload logo image', onChange:upload})),
        uploaded ? h('small', {style:muted}, 'Using an uploaded image.') : null,
        h('button', {type:'button', onClick:() => { controller.reset(); setMessage(''); }}, 'Reset logo and colours')),
      h('small', {style:muted}, 'The logo is cropped to a square when the side panel is collapsed. Without your own image the site default is used, and if no image loads, the DSH logo is shown.'),
      message ? h('small', {role:'status'}, message) : null,
      h('details', null,
        h('summary', null, 'Colours (' + Object.keys(CUSTOM_LIGHT_TOKENS).length + ')'),
        h('div', {style:{display:'grid', gap:'0.3rem', marginTop:'0.4rem'}},
          ...Object.entries(CUSTOM_LIGHT_TOKENS).map(([name, fallback]) => {
            const value = snapshot.colors[name] || '';
            return h('label', {key:name, style:{display:'grid', gridTemplateColumns:'1.2rem minmax(0,1fr) 9rem', gap:'0.5rem', alignItems:'center'}},
              h('span', {'aria-hidden':'true', style:{width:'1rem', height:'1rem', borderRadius:'3px',
                border:'1px solid var(--dsw-alias-border-l2)', background:value || fallback}}),
              h('code', {style:{fontSize:'0.8em', overflowWrap:'anywhere'}}, name.replace(/^--dsw-alias-/, '')),
              h('input', {type:'text', style:field, placeholder:fallback, 'aria-label':name, key:name + '=' + value, defaultValue:value,
                onBlur:event => { if (!controller.setColor(name, event.target.value)) setMessage('Not a colour: ' + event.target.value); }}));
          })))) : null,
    snapshot.persistenceError ? h('small', {role:'status'}, 'This browser could not save the setting; it applies until the page is reloaded.') : null);
}
// Square logo for the collapsed rail and the new-chat heading: the left of a wide logo, cropped.
function LogoMark({controller, size, className}) {
  const snapshot = useSnapshot(controller);
  const src = snapshot.effectiveLogo;
  return h('img', {src, onError:() => controller.markBroken(src), width:size, height:size, alt:'', className, draggable:false,
    style:{display:'block', width:size, height:size, objectFit:'cover', objectPosition:'left center', borderRadius:'4px'}});
}
// Beside the mark when the panel is open: the rest of a wide logo, so the square part is not shown twice.
function LogoName({controller}) {
  const snapshot = useSnapshot(controller);
  const [ratio, setRatio] = React.useState(0);
  const src = snapshot.effectiveLogo;
  const width = ratio ? Math.round(24 * ratio) - 24 : 0;
  return h('img', {src, onError:() => controller.markBroken(src), alt:'', draggable:false,
    onLoad:event => setRatio(event.target.naturalWidth / Math.max(1, event.target.naturalHeight)),
    style:{display:ratio && width < 8 ? 'none' : 'block', height:'24px', width:ratio ? width + 'px' : '0px', maxWidth:'100%',
      objectFit:'cover', objectPosition:'right center'}});
}
function apply(ctx) {
  let controller;
  const ensure = () => {
    if (!controller) {
      let storage;
      try { storage = globalThis.localStorage; } catch { /* Storage may be blocked; no auth fallback. */ }
      controller = createCustomTheme({theme:ctx.theme, tokens:CUSTOM_LIGHT_TOKENS, onThemeChange:listener => ctx.on('theme/change', listener), storage});
    }
    return controller;
  };
  ctx.effect(() => { ensure(); return () => { controller.dispose(); controller = undefined; }; }, 'Custom light theme: token layer');
  ctx.slots.inject('settings.general.item', () => ctx.slots.register({
    name:'settings.general.item', id:'custom-light', order:10.5, inject:() => ({controller:ensure()})
  }, CustomThemeRow));
  // Brand slots are filled only while the theme is on and Light is active; otherwise DSH's own logo shows.
  // A lower priority wins over the official brand plugin's registration.
  const components = {'sidebar.brand.mark':LogoMark, 'sidebar.brand.name':LogoName, 'conversation.hero.brand.mark':LogoMark};
  for (const name of BRAND_SLOTS) ctx.slots.inject(name, () => {
    const c = ensure(); let off = null;
    const sync = () => {
      const want = c.getSnapshot().brandActive;
      if (want && !off) off = ctx.slots.register({name, priority:-10, inject:() => ({controller:c})}, components[name]);
      else if (!want && off) { const remove = off; off = null; if (typeof remove === 'function') remove(); }
    };
    const unsubscribe = c.subscribe(sync); sync();
    return () => { unsubscribe(); if (typeof off === 'function') off(); off = null; };
  });
}

return {apply,inject};}});
