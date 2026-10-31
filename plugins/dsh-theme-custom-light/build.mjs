import fs from 'node:fs/promises';
const read = name => fs.readFile(new URL(name, import.meta.url), 'utf8');
// No artwork is bundled: the default logo is served by the deployment (see client.mjs DEFAULT_LOGO).
const parts = [await read('./src/palette.mjs'), await read('./src/controller.mjs'), (await read('./src/client.mjs')).replace(/^import .*;\n/gm, '')];
const body = parts.join('\n').replace(/^export /gm, '');
const bundle = 'window.__ModuleLoader__.load({id:"dsh-theme-custom-light",factory:(require)=>{const React=require("react");\n'+body+'\nreturn {apply,inject};}});\n';
await fs.mkdir(new URL('./lib/', import.meta.url), {recursive:true});
await fs.writeFile(new URL('./lib/client.js', import.meta.url), bundle);
