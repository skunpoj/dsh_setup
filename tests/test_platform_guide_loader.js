'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../container/platform_guide.cjs'),'utf8');
function load(content){const context={module:{exports:{}},Buffer,require(name){assert.equal(name,'node:fs');return {readFileSync(file,encoding){assert.equal(file,'/opt/dsh/container/PLATFORM_GUIDE.md');assert.equal(encoding,'utf8');return content;}};}};vm.runInNewContext(source,context);return context.module.exports.dshPlatformInstructions;}
const lf='# DSH shared platform guide\n\nDefault names: 8\n';
for(const content of [lf,lf.replaceAll('\n','\r\n')]){const instructions=load(content);assert.equal(instructions('Preserve my agent role'),lf+'\n\nPreserve my agent role');assert.equal(instructions(undefined),lf+'\n\n');}
assert.throws(()=>load('# Wrong guide\n')(''),/Invalid operator/);
assert.throws(()=>load(lf+'x'.repeat(32768))(''),/Invalid operator/);
console.log('Shared guide loader: LF/CRLF builds, preserved agent role, bounded valid guide and missing role passed.');
