'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),https=require('node:https'),path=require('node:path');
const {Broker}=require('../scripts/credential_broker');
test('actual TLS connector filters secrets, does not follow redirects, and masks error bodies',{skip:!process.env.DSH_CONNECTOR_TEST_TLS_DIR},async t=>{
 const directory=process.env.DSH_CONNECTOR_TEST_TLS_DIR,secret='SYNTHETIC_CREDENTIAL_CANARY_493857';let calls=0;
 const server=https.createServer({key:fs.readFileSync(path.join(directory,'key.pem')),cert:fs.readFileSync(path.join(directory,'cert.pem'))},(req,res)=>{
  calls++;assert.equal(req.headers.authorization,'Bearer '+secret);
  if(req.url==='/redirect'){res.writeHead(302,{Location:'https://evil.example/'});return res.end('{}');}
  if(req.url==='/error'){res.writeHead(401);return res.end(JSON.stringify({token:secret}));}
  res.setHeader('Set-Cookie','provider='+secret);res.end(JSON.stringify({value:'permitted',echo:secret,extra:'not-allowlisted'}));
 });await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(()=>new Promise(r=>server.close(r)));
 const broker=new Broker({vault:{},environment:'off',profiles:{},audit:()=>true});
 const profile={baseUrl:'https://127.0.0.1:'+server.address().port,allowedAddresses:['127.0.0.1'],caFile:path.join(directory,'cert.pem')};
 const op={method:'GET',path:'/',parameters:{},responseFields:['value','echo']};
 const result=await broker.connect(profile,op,{},secret);assert.equal(result.value,'permitted');assert.equal(result.echo,'[REDACTED]');assert.equal(result.extra,undefined);assert(!JSON.stringify(result).includes(secret));
 await assert.rejects(broker.connect(profile,{...op,path:'/redirect'},{},secret));assert.equal(calls,2);
 await assert.rejects(broker.connect(profile,{...op,path:'/error'},{},secret),e=>!e.message.includes(secret));assert.equal(calls,3);
 await assert.rejects(broker.connect({...profile,allowedAddresses:['10.0.0.1']},op,{},secret));assert.equal(calls,3);
});
