import * as React from 'react';
import { createCustomTheme } from './controller.mjs';
import { CUSTOM_LIGHT_TOKENS } from './palette.mjs';
export const inject = ['theme', 'slots'];
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
export function apply(ctx) {
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
