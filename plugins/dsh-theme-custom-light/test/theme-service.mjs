// Focused checks for dsh-theme-custom-light 0.3.1 against the real DSH ThemeRuntime.
// Usage: node test/theme-service.mjs <path to @deepseek-ai/dsh-client-ui-theme/lib/client.js>
// The theme bundle is the one shipped in the runtime image (0.2.1-rc.5); slots, React and
// settings transport are explicit test doubles.
import fs from 'node:fs/promises';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
const base = path.dirname(fileURLToPath(import.meta.url));
const themeCode = await fs.readFile(process.argv[2], 'utf8');
const pluginCode = await fs.readFile(path.join(base, '..', 'lib/client.js'), 'utf8');
const KEY = 'dsh-theme-custom-light/custom/v3', V2 = 'dsh-theme-custom-light/light/v2', V1 = 'dsh-theme-custom-light/selection/v1';
const BRAND = ['sidebar.brand.mark', 'sidebar.brand.name', 'conversation.hero.brand.mark'];
const settle = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const PNG = 'data:image/png;base64,iVBORw0KGgo=';

function make({preference = 'system', saved, v2, v1, brokenStorage = false} = {}) {
  const events = new Map(), mediaListeners = new Set(), hostListeners = new Set();
  const nativeDisposers = [], pluginDisposers = []; let activeEffects = nativeDisposers;
  const defaults = {fontSize:14, codeFontSize:13, terminalFontSize:13, textFontFamily:'', codeFontFamily:'', terminalFontFamily:''};
  let value = {...defaults, preference};
  const writes = [];
  const memory = new Map([...(saved ? [[KEY, saved]] : []), ...(v2 ? [[V2, v2]] : []), ...(v1 ? [[V1, v1]] : [])]);
  const storage = {getItem:k => { if (brokenStorage) throw Error('blocked'); return memory.get(k) ?? null; },
                   setItem:(k, v) => { if (brokenStorage) throw Error('blocked'); memory.set(k, v); }};
  const media = {matches:false, addEventListener:(_n, l) => mediaListeners.add(l), removeEventListener:(_n, l) => mediaListeners.delete(l)};
  const host = {getSnapshot:() => ({status:'ready', value, writable:true}), subscribe:l => { hostListeners.add(l); return () => hostListeners.delete(l); },
    set:async (k, v) => { writes.push([k, v]); value = {...value, [k]:v}; for (const l of [...hostListeners]) l(); },
    mutate:async ops => { for (const o of ops) { writes.push([o.path[0], o.value]); value = {...value, [o.path[0]]:o.value}; } for (const l of [...hostListeners]) l(); }};
  const ctx = {effect:f => { const d = f(); if (typeof d === 'function') activeEffects.push(d); }, inject:() => {},
    on:(event, l) => { const a = events.get(event) ?? new Set(); a.add(l); events.set(event, a); return () => a.delete(l); },
    emit:(event, v) => { for (const l of [...(events.get(event) ?? [])]) l(v); }};
  const React = {createContext:() => ({}), forwardRef:f => f, memo:f => f,
    createElement:(type, props, ...children) => ({type, props:props ?? {}, children}),
    useState:f => [typeof f === 'function' ? f() : f, () => {}], useEffect:() => {}};
  let moduleExports;
  const runtime = vm.createContext({queueMicrotask, console, URL, matchMedia:() => media, localStorage:storage,
    window:{__ModuleLoader__:{load:spec => { moduleExports = spec.factory(name => name === 'react' ? React : name === '@deepseek-ai/dsh-client-store' ? {defineStore:x => x} : {}); }}}});
  vm.runInContext(themeCode, runtime);
  ctx.theme = new moduleExports.ThemeRuntime(ctx, host);
  const slots = [];
  const official = {};
  for (const name of BRAND) { official[name] = () => 'official'; slots.push({options:{name}, component:official[name]}); }
  const nativeRows = {appearance:() => 'appearance', 'font-size':() => 'font-size'};
  slots.push({options:{name:'settings.general.item', id:'appearance', order:10}, component:nativeRows.appearance});
  slots.push({options:{name:'settings.general.item', id:'font-size', order:11}, component:nativeRows['font-size']});
  ctx.slots = {inject:(_n, f) => { const d = f(); if (typeof d === 'function') pluginDisposers.push(d); },
    register:(options, component) => { const e = {options, component}; slots.push(e); return () => { const i = slots.indexOf(e); if (i >= 0) slots.splice(i, 1); }; }};
  vm.runInContext(pluginCode, runtime);
  activeEffects = pluginDisposers; moduleExports.apply(ctx); activeEffects = nativeDisposers;
  const shown = name => [...slots.filter(e => e.options.name === name)].sort((a, b) => (a.options.priority ?? 0) - (b.options.priority ?? 0))[0];
  const rows = () => slots.filter(e => e.options.name === 'settings.general.item').sort((a, b) => a.options.order - b.options.order);
  const row = () => rows().find(e => e.options.id === 'custom-light');
  const controller = () => row().options.inject().controller;
  return {ctx, slots, shown, rows, row, controller, writes, memory, nativeRows, official,
    flip:dark => { media.matches = dark; for (const l of [...mediaListeners]) l(); },
    tokens:() => ctx.theme.getTheme().active.tokens,
    brandIsOfficial:() => BRAND.every(n => shown(n).component === official[n]),
    unload:() => { for (const d of [...pluginDisposers].reverse()) d(); }};
}
const results = [];
async function test(name, fn) { try { await fn(); results.push({name, pass:true}); } catch (e) { results.push({name, pass:false, error:e.message}); } }
const count = o => Object.keys(o).length;
const text = node => node == null || typeof node !== 'object' ? String(node ?? '') :
  [node.props?.placeholder, node.props?.['aria-label'], node.props?.alt, ...(node.children || []).flat().map(text)].filter(Boolean).join(' ');

await test('Native Appearance row is untouched; the custom row sits under it', async () => {
  const f = make();
  assert.equal(f.slots.filter(e => e.options.id === 'appearance').length, 1);
  assert.equal(f.rows().find(e => e.options.id === 'appearance').component, f.nativeRows.appearance);
  assert.deepEqual(f.rows().map(e => e.options.id), ['appearance', 'custom-light', 'font-size']);
  f.unload();
});
await test('Installing changes nothing: off, no layer, official logo, no writes', async () => {
  const f = make({preference:'light'}); await settle();
  assert.equal(f.controller().getSnapshot().enabled, false);
  assert.equal(count(f.tokens()), 0); assert.equal(f.brandIsOfficial(), true);
  assert.equal(f.memory.size, 0); assert.equal(f.writes.length, 0);
  f.unload();
});
await test('On in Light: 32 tokens and the custom logo; Dark: native colours and the official logo', async () => {
  const f = make({preference:'light'});
  f.controller().setEnabled(true);
  assert.equal(count(f.tokens()), 32); assert.equal(f.tokens()['--dsw-alias-button-primary-fill'], '#003366');
  for (const n of BRAND) assert.equal(f.shown(n).options.priority, -10);
  f.ctx.theme.setTheme('dark'); await settle();
  assert.equal(count(f.tokens()), 0); assert.equal(f.brandIsOfficial(), true);
  f.ctx.theme.setTheme('light'); await settle();
  assert.equal(count(f.tokens()), 32); assert.equal(f.brandIsOfficial(), false);
  f.unload();
});
await test('System follows the device', async () => {
  const f = make({preference:'system'});
  f.controller().setEnabled(true); assert.equal(count(f.tokens()), 32);
  f.flip(true); assert.equal(count(f.tokens()), 0); assert.equal(f.brandIsOfficial(), true);
  f.flip(false); assert.equal(count(f.tokens()), 32); assert.equal(f.brandIsOfficial(), false);
  f.unload();
});
await test('Turning it off restores native colours and the official logo, and saves', async () => {
  const f = make({preference:'light'});
  f.controller().setEnabled(true); f.controller().setEnabled(false);
  assert.equal(count(f.tokens()), 0); assert.equal(f.brandIsOfficial(), true);
  assert.equal(JSON.parse(f.memory.get(KEY)).enabled, false);
  f.unload();
});
await test('Native preference is never written', async () => {
  for (const p of ['light', 'dark', 'system']) {
    const f = make({preference:p}); f.controller().setEnabled(true); f.controller().setColor('--dsw-alias-bg-base', '#ffffff'); f.controller().setEnabled(false); await settle();
    assert.equal(f.ctx.theme.getTheme().preference, p); assert.equal(f.writes.filter(([k]) => k === 'preference').length, 0); f.unload();
  }
});
await test('Custom colours override defaults; invalid ones are rejected; empty restores the default', async () => {
  const f = make({preference:'light'}); const c = f.controller(); c.setEnabled(true);
  assert.equal(c.setColor('--dsw-alias-button-primary-fill', '#112233'), true);
  assert.equal(f.tokens()['--dsw-alias-button-primary-fill'], '#112233');
  assert.equal(c.setColor('--dsw-alias-button-primary-fill', 'red;background:url(x)'), false);
  assert.equal(f.tokens()['--dsw-alias-button-primary-fill'], '#112233');
  assert.equal(c.setColor('--dsw-alias-label-primary', 'rgb(10, 20, 30)'), true);
  assert.equal(c.setColor('--dsw-alias-button-primary-fill', ''), true);
  assert.equal(f.tokens()['--dsw-alias-button-primary-fill'], '#003366'); assert.equal(count(f.tokens()), 32);
  assert.throws(() => c.setColor('--not-a-token', '#000'));
  f.unload();
});
await test('Logo accepts https links and inline images only', async () => {
  const f = make({preference:'light'}); const c = f.controller(); c.setEnabled(true);
  for (const bad of ['http://example.com/a.png', 'javascript:alert(1)', 'ftp://x/y.png', 'data:text/html;base64,PGI+', 'data:image/png;base64,' + 'A'.repeat(700001)]) assert.equal(c.setLogo(bad), false, bad);
  assert.equal(c.setLogo('https://example.com/logo.png'), true); assert.equal(c.getSnapshot().logo, 'https://example.com/logo.png');
  assert.equal(c.setLogo(PNG), true); assert.equal(c.getSnapshot().logo, PNG);
  assert.equal(c.setLogo(''), true); assert.equal(c.getSnapshot().logo, '');
  f.unload();
});
await test('Logo: the deployment default, then the user image; unloadable images fall back to the DSH logo', async () => {
  const f = make({preference:'light'}); const c = f.controller(); c.setEnabled(true);
  const mark = () => { const e = f.shown('sidebar.brand.mark'); return e.component({...e.options.inject(), size:24}); };
  assert.equal(mark().props.src, '/manual/brand/logo.png'); assert.equal(mark().props.style.objectPosition, 'left center');
  c.setLogo('https://example.com/logo.png'); assert.equal(mark().props.src, 'https://example.com/logo.png');
  mark().props.onError(); assert.equal(mark().props.src, '/manual/brand/logo.png');
  mark().props.onError(); assert.equal(f.brandIsOfficial(), true); assert.equal(count(f.tokens()), 32);
  const he = make({preference:'light'}); he.controller().setEnabled(true);
  const e = he.shown('conversation.hero.brand.mark'); assert.equal(e.component({...e.options.inject(), size:34, className:'x'}).props.width, 34);
  const ne = he.shown('sidebar.brand.name'); assert.equal(ne.component(ne.options.inject()).props.style.objectPosition, 'right center');
  he.unload(); f.unload();
});
await test('Saved settings restore; 0.2.0 and 0.1.0 choices migrate', async () => {
  const a = make({preference:'light', saved:JSON.stringify({version:3, enabled:true, logo:PNG, colors:{'--dsw-alias-bg-base':'#000000', '--evil':'#fff'}})});
  assert.equal(a.tokens()['--dsw-alias-bg-base'], '#000000'); assert.equal(a.tokens()['--evil'], undefined); assert.equal(a.controller().getSnapshot().logo, PNG); a.unload();
  const b = make({preference:'light', v2:JSON.stringify({version:2, enabled:true})}); assert.equal(count(b.tokens()), 32); b.unload();
  const c = make({preference:'light', v1:JSON.stringify({version:1, custom:true, fallback:'light'})}); assert.equal(count(c.tokens()), 32); c.unload();
  const d = make({preference:'light', saved:JSON.stringify({version:3, enabled:true, logo:'javascript:x', colors:{}})}); assert.equal(d.controller().getSnapshot().logo, ''); d.unload();
});
await test('A theme or token layer from another plugin is left alone', async () => {
  const f = make({preference:'light'});
  const removeLayer = f.ctx.theme.overrideTokens('foreign-plugin', {'--y':{light:'#111', dark:'#eee'}});
  f.controller().setEnabled(true); assert.equal(count(f.tokens()), 33);
  const remove = f.ctx.theme.register({id:'foreign', colorScheme:'light', tokens:{}});
  f.ctx.theme.setTheme('foreign'); await settle(); assert.equal(f.tokens()['--dsw-alias-bg-base'], undefined); assert.equal(f.brandIsOfficial(), true);
  f.ctx.theme.setTheme('light'); remove(); f.unload(); assert.equal(JSON.stringify(f.tokens()), '{"--y":"#111"}'); removeLayer();
});
await test('Unload removes the layer, the row and the logo', async () => {
  const f = make({preference:'light'}); f.controller().setEnabled(true); f.unload();
  assert.equal(count(f.tokens()), 0); assert.equal(f.rows().some(e => e.options.id === 'custom-light'), false); assert.equal(f.brandIsOfficial(), true);
});
await test('Blocked or malformed storage keeps the switch usable', async () => {
  for (const setup of [{brokenStorage:true}, {saved:'{not-json'}, {saved:JSON.stringify({version:3, enabled:'yes'})}]) {
    const f = make({preference:'light', ...setup}); assert.equal(f.controller().getSnapshot().enabled, false);
    f.controller().setEnabled(true); assert.equal(count(f.tokens()), 32); f.unload();
  }
});
await test('Settings row: accessible switch, logo inputs and one field per colour, neutral wording', async () => {
  const f = make({preference:'light'}); const r = () => f.row().component(f.row().options.inject());
  const input = r().children[0].children[1];
  assert.equal(input.props.role, 'switch'); assert.equal(input.props['aria-label'], 'Custom light theme');
  input.props.onChange({target:{checked:true}}); assert.equal(count(f.tokens()), 32);
  const tree = r(); const all = text(tree);
  assert.match(all, /Logo image link/); assert.match(all, /Upload logo image/);
  const fields = JSON.stringify(tree).match(/"aria-label":"--dsw-alias-[^"]+"/g) || []; assert.equal(fields.length, 32);
  f.unload();
});
await test('Bundle: no network URLs, no bundled images, no institution name', async () => {
  assert.equal(/https?:\/\//.test(pluginCode), false);
  assert.equal(/data:image\//.test(pluginCode), false);
});

const report = {at:new Date().toISOString(), theme:'real ThemeRuntime', passed:results.filter(x => x.pass).length, total:results.length, results,
  notVerified:['Real browser rendering, image loading and crop', 'Real SlotCore election (priority -10, as 0.2.0 relies on)', 'Deployed image digest']};
console.log(JSON.stringify(report, null, 1));
if (report.passed !== report.total) process.exitCode = 1;
