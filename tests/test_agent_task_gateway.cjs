'use strict';
const assert=require('node:assert/strict'),http=require('http'),crypto=require('crypto');
const gateway=require('../scripts/agent_task_gateway');
const token='r'.repeat(32),csrf='a'.repeat(64);let observed=[];
function listen(server){return new Promise(resolve=>server.listen(0,'127.0.0.1',()=>resolve(server.address().port)));}
function call(port,path,{method='GET',headers={},body=''}={}){return new Promise((resolve,reject)=>{const r=http.request({host:'127.0.0.1',port,path,method,headers:{...headers,...(body?{'content-length':Buffer.byteLength(body)}:{})}},s=>{let data='';s.on('data',b=>data+=b);s.on('end',()=>resolve({status:s.statusCode,headers:s.headers,body:data}))});r.on('error',reject);if(body)r.write(body);r.end()})}
async function main(){
 const upstream=http.createServer((req,res)=>{let body='';req.on('data',b=>body+=b);req.on('end',()=>{observed.push({url:req.url,method:req.method,authorization:req.headers.authorization,body});res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify({runtimes:['sdk'],backends:[{id:'private',enabled:true},{id:'openshell',enabled:false,reason:'gates'}]}))})});
 const upstreamPort=await listen(upstream),session={agentCsrf:csrf};let authenticated=true;
 const server=http.createServer((req,res)=>{const parsed=new URL(req.url,'https://dsh.test');gateway.handle(req,res,{pathname:parsed.pathname,query:parsed.search,target:{host:'127.0.0.1'},token,user:'alice',session,trustedHost:'dsh.test',authorized:()=>authenticated,upstreamPort}).then(handled=>{if(!handled){res.writeHead(404);res.end()}})});
 // Test-only injection keeps production fixed at 7682 without weakening the public contract.
 const original=http.request;http.request=function(options,...args){if(options.port===7682)options={...options,port:upstreamPort};return original.call(this,options,...args)};
 const port=await listen(server);
 try{
  let r=await call(port,'/agent-tasks');assert.equal(r.status,200);assert.match(r.body,/DSH Python SDK/);assert.match(r.body,/>Kilo</);assert.match(r.body,/Optional handoff/);assert.match(r.body,/OpenShell unavailable/);
  r=await call(port,'/api/agent-tasks/capabilities');assert.equal(r.status,403);
  r=await call(port,'/api/agent-tasks/capabilities',{headers:{'x-dsh-agent-csrf':csrf}});assert.equal(r.status,200);assert.equal(observed.at(-1).authorization,'Bearer '+token);
  const body=JSON.stringify({runtime:'sdk',backend:'private',project:'.',prompt:'read README',writes:false,approved:true});
  r=await call(port,'/api/agent-tasks',{method:'POST',headers:{'x-dsh-agent-csrf':csrf,origin:'https://evil.test','content-type':'application/json'},body});assert.equal(r.status,403);
  r=await call(port,'/api/agent-tasks',{method:'POST',headers:{'x-dsh-agent-csrf':csrf,origin:'https://dsh.test','content-type':'application/json'},body});assert.equal(r.status,200);assert.equal(observed.at(-1).body,body);
  const approval='/api/agent-tasks/'+'b'.repeat(32)+'/approve';
  r=await call(port,approval,{method:'POST',headers:{'x-dsh-agent-csrf':csrf,origin:'https://dsh.test'},body:'{"approved":true}'});
  assert.equal(r.status,200);assert.equal(observed.at(-1).url,'/v1/tasks/'+'b'.repeat(32)+'/approve');
  const count=observed.length;
  r=await call(port,approval,{method:'POST',headers:{'x-dsh-agent-csrf':csrf,origin:'https://evil.test'},body:'{"approved":true}'});
  assert.equal(r.status,403);assert.equal(observed.length,count);
  authenticated=false;r=await call(port,'/agent-tasks');assert.equal(r.status,401);assert.doesNotMatch(r.body,/csrfToken|Managed agent task/);
  console.log(JSON.stringify({passed:8,failed:0,upstreamRequests:observed.length}));
 }finally{http.request=original;await new Promise(r=>server.close(r));await new Promise(r=>upstream.close(r));}
}
main().catch(e=>{console.error(e);process.exitCode=1});
