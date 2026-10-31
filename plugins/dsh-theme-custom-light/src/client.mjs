import * as React from 'react';
import { createThemeController, CUSTOM_ID } from './controller.mjs';
import { CUSTOM_LIGHT_TOKENS } from './palette.mjs';
export const inject = ['theme', 'slots', 'configForms'];
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
export function apply(ctx) {
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
