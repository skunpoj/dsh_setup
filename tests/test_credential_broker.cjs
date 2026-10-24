'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const {Broker,destinationAllowed,equal}=require('../scripts/credential_broker');
function fixture(environment='off'){
 const state=new Map(),audit=[],calls=[];let clock=1000;
 const vault={async read(user){return structuredClone(state.get(user)||{items:{},version:0});},async write(user,x){state.set(user,{...structuredClone(x),version:x.version+1});}};
 const profiles={internal:{label:'Fixture',environments:['off'],operations:{read:{method:'GET',parameters:{key:'[a-z]+'}},write:{method:'POST',parameters:{key:'[a-z]+'}}}},external:{label:'External',environments:['on'],operations:{read:{method:'GET',parameters:{}}}}};
 const broker=new Broker({vault,environment,profiles,now:()=>clock,audit:e=>{audit.push(e);return true;},dispatch:async(p,o,params,secret)=>{calls.push({o,params});return {value:'permitted-result'};}});
 const save=(owner='alice',id='repository')=>broker.handle(owner,'save',{id,profile:'internal',workspace:'one',operations:['read','write'],expiresAt:10000,secret:'synthetic-canary-credential'});
 return {broker,state,audit,calls,save,advance:()=>clock=20000};
}
test('secret values are absent from metadata and cross-user access is denied',async()=>{
 const f=fixture();await f.save();const a=await f.broker.handle('alice','list');assert.equal(a.credentials.length,1);assert(!JSON.stringify(a).includes('synthetic-canary'));
 assert.equal((await f.broker.handle('bob','list')).credentials.length,0);
 await assert.rejects(f.broker.handle('bob','execute',{id:'repository',workspace:'one',operation:'read',parameters:{key:'a'}}));
 await assert.rejects(f.broker.handle('alice','execute',{id:'repository',workspace:'two',operation:'read',parameters:{key:'a'}}));
 await assert.rejects(f.broker.handle('alice','execute',{id:'repository',workspace:'one',operation:'delete',parameters:{key:'a'}}));
 assert.equal(f.calls.length,0);assert(!JSON.stringify(f.audit).includes('synthetic-canary'));
});
test('explicit environment, expiration and disable/delete boundaries',async()=>{
 const f=fixture();await assert.rejects(f.broker.handle('alice','save',{id:'repo',profile:'external',workspace:'one',secret:'synthetic-canary',expiresAt:10000,operations:['read']}));
 await f.save();await f.broker.handle('alice','disable',{id:'repository'});await assert.rejects(f.broker.handle('alice','execute',{id:'repository',workspace:'one',operation:'read',parameters:{key:'a'}}));
 await f.broker.handle('alice','delete',{id:'repository'});assert.equal((await f.broker.handle('alice','list')).credentials.length,0);
 await f.save();f.advance();await assert.rejects(f.broker.handle('alice','execute',{id:'repository',workspace:'one',operation:'read',parameters:{key:'a'}}));
});
test('write approval is exact, owner-bound and atomically consumed',async()=>{
 const f=fixture();await f.save();const input={id:'repository',workspace:'one',operation:'write',parameters:{key:'a'}};
 const pending=await f.broker.handle('alice','execute',input);assert(pending.approvalRequired);assert.equal(f.calls.length,0);
 await assert.rejects(f.broker.handle('bob','approve',{id:pending.approvalId}));
 await f.broker.handle('alice','approve',{id:pending.approvalId});
 await assert.rejects(f.broker.handle('alice','execute',{...input,parameters:{key:'b'},approvalId:pending.approvalId}));
 const concurrent=await Promise.allSettled([1,2].map(()=>f.broker.handle('alice','execute',{...input,approvalId:pending.approvalId})));
 assert.equal(concurrent.filter(x=>x.status==='fulfilled').length,1);assert.equal(f.calls.length,1);
});
test('revocation clears pending grants and required audit fails closed',async()=>{
 const f=fixture();await f.save();const input={id:'repository',workspace:'one',operation:'write',parameters:{key:'a'}};
 const pending=await f.broker.handle('alice','execute',input);await f.broker.handle('alice','disable',{id:'repository'});await assert.rejects(f.broker.handle('alice','approve',{id:pending.approvalId}));
 const g=fixture();await g.save();g.broker.audit=()=>false;await assert.rejects(g.broker.handle('alice','execute',{...input,operation:'read'}));assert.equal(g.calls.length,0);
});
test('concurrent saves preserve both connections; unsafe identifiers and parameters fail',async()=>{
 const f=fixture();await Promise.all([f.save('alice','one'),f.save('alice','two')]);assert.equal((await f.broker.handle('alice','list')).credentials.length,2);
 await assert.rejects(f.save('alice','__proto__'));await assert.rejects(f.broker.handle('alice','execute',{id:'one',workspace:'one',operation:'read',parameters:{key:'a',url:'https://evil.example'}}));
});
test('public destinations reject metadata, loopback, private, benchmark and multicast addresses',()=>{
 for(const ip of ['127.0.0.1','169.254.169.254','10.0.0.1','172.16.0.1','192.168.0.1','198.18.0.1','224.0.0.1','::1'])assert.equal(destinationAllowed(ip,{network:'public'}),false,ip);
 assert.equal(destinationAllowed('8.8.8.8',{network:'public'}),true);assert.equal(destinationAllowed('10.0.0.1',{allowedAddresses:['10.0.0.2']}),false);assert.equal(equal('é','a'),false);
});
test('encrypted entry is owner/action-context bound and plaintext entry is rejected in production mode',async()=>{
 const crypto=require('node:crypto'),{envelopeAAD}=require('../scripts/credential_broker');const {privateKey,publicKey}=crypto.generateKeyPairSync('rsa',{modulusLength:2048});
 const f=fixture();f.broker.encryptionKey=privateKey;
 const input={id:'encrypted',profile:'internal',workspace:'one',operations:['read'],expiresAt:10000,scopes:{}};
 const aes=crypto.randomBytes(32),iv=crypto.randomBytes(12),c=crypto.createCipheriv('aes-256-gcm',aes,iv);c.setAAD(envelopeAAD('alice','off',input));
 input.secretEnvelope={key:crypto.publicEncrypt({key:publicKey,oaepHash:'sha256'},aes).toString('base64'),iv:iv.toString('base64'),body:Buffer.concat([c.update('SYNTHETIC_ENCRYPTED_CANARY'),c.final(),c.getAuthTag()]).toString('base64')};
 await assert.rejects(f.broker.handle('bob','save',input));await assert.rejects(f.broker.handle('alice','save',{...input,workspace:'two'}));
 await assert.rejects(f.broker.handle('alice','save',{...input,secret:'plaintext-must-fail'}));
 assert.equal((await f.broker.handle('alice','save',input)).id,'encrypted');assert(!JSON.stringify(await f.broker.handle('alice','list')).includes('SYNTHETIC_ENCRYPTED_CANARY'));
});
test('resource fences and request-rate limits cannot be expanded by tool arguments',async()=>{
 const f=fixture();f.broker.profiles.scoped={label:'Scoped',environments:['off'],scopeParameters:{key:'[a-z]+'},operations:{read:{method:'GET',parameters:{key:'[a-z]+'}}}};
 await f.broker.handle('alice','save',{id:'one',profile:'scoped',workspace:'one',operations:['read'],scopes:{key:'allowed'},secret:'synthetic-canary',expiresAt:10000});
 await assert.rejects(f.broker.handle('alice','execute',{id:'one',workspace:'one',operation:'read',parameters:{key:'other'}}));assert.equal(f.calls.length,0);
 for(let i=0;i<21;i++)await f.broker.handle('alice','execute',{id:'one',workspace:'one',operation:'read',parameters:{key:'allowed'}}).catch(()=>{});
 assert(f.calls.length<=20);
});
