'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
test('actual configured demo aliases pass the unmodified routing-name predicate',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../runtime/auth_proxy.js'),'utf8'),bootstrap=fs.readFileSync(path.join(__dirname,'bootstrap.js'),'utf8');
 const predicate=source.match(/function validAppName\(name\) \{[^\n]+\}/)[0];
 const valid=vm.runInNewContext('('+predicate+')');
 const aliases=vm.runInNewContext(bootstrap.match(/const aliases=(\[[^;\n]+\]);/)[1]);
 assert.equal(aliases.length,2);for(const name of aliases)assert(valid(name),'Configured alias is reserved: '+name);
 for(const name of ['dsh-app-signin-gated-test','dsh-app-signin-public-test','dsh','terminal','api'])assert.equal(valid(name),false,'Reserved guard must remain intact');
 assert(!source.includes('password hashes are mirrored'));
});
