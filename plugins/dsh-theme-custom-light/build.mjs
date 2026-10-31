import fs from 'node:fs/promises';
const palette = await fs.readFile(new URL('./src/palette.mjs', import.meta.url), 'utf8');
const controller = await fs.readFile(new URL('./src/controller.mjs', import.meta.url), 'utf8');
const client = await fs.readFile(new URL('./src/client.mjs', import.meta.url), 'utf8');
const body = [palette, controller, client.replace(/^import .*;\n/gm, '')].join('\n').replace(/^export /gm, '');
const bundle = 'window.__ModuleLoader__.load({id:"dsh-theme-custom-light",factory:(require)=>{const React=require("react");\n'+body+'\nreturn {apply,inject};}});\n';
await fs.mkdir(new URL('./lib/', import.meta.url), {recursive:true});
await fs.writeFile(new URL('./lib/client.js', import.meta.url), bundle);
