window.__ModuleLoader__.load({id:"dsh-theme-custom-light",factory:(require)=>{const React=require("react");
// Palette aliases from the gateway login stylesheet scripts/platform.css.
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

// DSH 0.2.1-rc.2: public theme/configForms APIs only. No DOM or credential access.
const CUSTOM_ID = 'custom-light';
const STORAGE_KEY = 'dsh-theme-custom-light/selection/v1';
const NATIVE = new Set(['light', 'dark', 'system']);
function createThemeController({theme, nativeForm, onThemeChange, storage, enqueue = queueMicrotask}) {
  let disposed = false, queued = false, persistenceError = !storage;
  let custom = false;
  let fallback = NATIVE.has(theme.getTheme().preference) ? theme.getTheme().preference : 'system';
  try { const value = JSON.parse(storage?.getItem(STORAGE_KEY) || 'null');
    if (value?.version === 1 && value.custom === true && NATIVE.has(value.fallback)) {
      custom = true; fallback = value.fallback;
    }
  } catch { persistenceError = true; }
  const listeners = new Set();
  const notify = () => { for (const listener of [...listeners]) listener(); };
  const persist = () => {
    try { storage?.setItem(STORAGE_KEY, JSON.stringify({version:1, custom, fallback})); }
    catch { persistenceError = true; }
  };
  const restore = () => {
    queued = false;
    if (disposed || !custom) return;
    const current = theme.getTheme().preference;
    // A foreign registered custom theme has its own owner; never fight it.
    if (!NATIVE.has(current) && current !== CUSTOM_ID) { custom = false; persist(); notify(); return; }
    if (current !== CUSTOM_ID) theme.setTheme(CUSTOM_ID);
    notify();
  };
  const scheduleRestore = () => { if (!queued) { queued = true; enqueue(restore); } };
  const off = onThemeChange(() => {
    // Host settings adoption may restore its built-in id after fonts or initial load.
    // Defer so all subscribers finish the old event before the custom snapshot emits.
    if (custom && theme.getTheme().preference !== CUSTOM_ID) scheduleRestore();
    notify();
  });
  if (custom) scheduleRestore();
  return {
    getSnapshot: () => ({preference:theme.getTheme().preference, custom, persistenceError}),
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    choose(id) {
      if (disposed) throw new Error('theme controller is disposed');
      if (id !== CUSTOM_ID && !NATIVE.has(id)) throw new Error('unknown appearance option');
      if (id === CUSTOM_ID) {
        if (!custom) {
          const current = theme.getTheme().preference;
          if (NATIVE.has(current)) fallback = current;
        }
        custom = true;
      } else { custom = false; fallback = id; }
      persist(); theme.setTheme(id); notify();
    },
    dispose() {
      if (disposed) return;
      disposed = true; off(); listeners.clear();
      if (theme.getTheme().preference === CUSTOM_ID) {
        const native = nativeForm?.getSnapshot().value?.preference;
        theme.setTheme(NATIVE.has(native) ? native : fallback);
      }
    }
  };
}

const inject = ['theme', 'slots', 'configForms'];
function Appearance({controller}) {
  const [snapshot, setSnapshot] = React.useState(() => controller.getSnapshot());
  React.useEffect(() => {
    const sync = () => setSnapshot(controller.getSnapshot());
    const off = controller.subscribe(sync); sync(); return off;
  }, [controller]);
  const value = snapshot.custom ? CUSTOM_ID : snapshot.preference;
  return React.createElement('div', {style:{display:'grid',gap:'0.5rem',paddingBlock:'0.5rem'}},
    React.createElement('label', {style:{display:'flex',alignItems:'center',justifyContent:'space-between',gap:'1rem'}},
      React.createElement('span', null, 'Appearance'),
      React.createElement('select', {value, 'aria-label':'Appearance', onChange:event => controller.choose(event.target.value)},
        ...[['light','Light'],['dark','Dark'],['system','System'],[CUSTOM_ID,'Custom Light']].map(([id,label]) =>
          React.createElement('option',{key:id,value:id},label)))),
    React.createElement('small',null,'System follows your device. Custom uses the custom light palette; its selection is saved in this browser only.'),
    snapshot.persistenceError ? React.createElement('small',{role:'status'},'The browser could not read or save the custom selection. This session can still change appearance.') : null);
}
function apply(ctx) {
  let controller;
  ctx.effect(() => {
    const unregister = ctx.theme.register({id:CUSTOM_ID,colorScheme:'light',tokens:CUSTOM_LIGHT_TOKENS});
    let storage;
    try { storage = globalThis.localStorage; } catch { /* Storage may be blocked; no auth fallback. */ }
    controller = createThemeController({theme:ctx.theme,nativeForm:ctx.configForms.get('ui-theme'),
      onThemeChange:listener => ctx.on('theme/change',listener),storage});
    return () => { controller.dispose(); unregister(); };
  }, 'custom light theme: registry and reversible browser selection');
  // Public list-slot shadowing replaces only Appearance; unloading reveals the original row.
  // Fonts and all other settings rows remain owned by the native plugins.
  ctx.slots.inject('settings.general.item', () => ctx.slots.register({
    name:'settings.general.item',id:'appearance',order:10,priority:-10,
    inject:() => ({controller})
  }, Appearance));
}

return {apply,inject};}});
