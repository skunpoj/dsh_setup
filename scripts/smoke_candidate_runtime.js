// Boot the installed upstream web server against disposable state only.
const fs=require('fs'),os=require('os'),path=require('path'),http=require('http'),assert=require('assert'),{spawn}=require('child_process');
const home=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-candidate-'));
const seed=process.env.DSH_CANDIDATE_SEED || '/opt/dsh/seed/dsh-home';
fs.cpSync(seed,home,{recursive:true});
const port=31997;let token='',cookie='',log='',closed=false;
const child=spawn('dsh',['web','--host','127.0.0.1','--port',String(port),'--no-open','--trusted-host','127.0.0.1'],{
 env:{...process.env,DSH_HOME:home},stdio:['ignore','pipe','pipe']});
child.on('exit',()=>{closed=true;});
const collect=b=>{log=(log+b.toString()).slice(-16000);const m=log.match(/token=([A-Za-z0-9_-]+)/);if(m)token=m[1];};
child.stdout.on('data',collect);child.stderr.on('data',collect);
function request(method,url,body='',auth=true,host='127.0.0.1'){
 return new Promise((resolve,reject)=>{const r=http.request({host:'127.0.0.1',port,path:url,method,
 headers:{host,...(auth?{cookie}:{}),'content-type':'application/json','content-length':Buffer.byteLength(body)}},res=>{
 let text='';res.on('data',b=>text+=b);res.on('end',()=>resolve({status:res.statusCode,text,cookies:res.headers['set-cookie']||[]}));});
 r.setTimeout(5000,()=>r.destroy(new Error('Candidate HTTP timeout')));r.on('error',reject);r.end(body);});
}
async function rpc(method,args={}){const r=await request('POST','/api/'+method,JSON.stringify({type:'client-request',rpcId:'candidate-smoke',method,payload:{args}}));
 assert.equal(r.status,200,'Candidate RPC HTTP failed');return JSON.parse(r.text);}
(async()=>{try{
 const until=Date.now()+90000;
 while(!token && !closed && Date.now()<until)await new Promise(r=>setTimeout(r,250));
 assert(token && !closed,'Candidate web server did not produce a launch token; inspect compatibility locally without exposing startup logs');
 const handshake=await request('GET','/?token='+encodeURIComponent(token),'',false);
 cookie=handshake.cookies.filter(c=>c.startsWith('dsh-auth-')).map(c=>c.split(';')[0]).join('; ');
 assert(cookie,'Candidate launch token did not mint an authentication cookie');
 let list;while(Date.now()<until){try{list=await rpc('session/list',{_request:{}});if(list.result?.ok)break;}catch{}await new Promise(r=>setTimeout(r,250));}
 assert.equal(list?.result?.ok,true,'Actual session-list RPC failed');
 const catalog=await rpc('session/modelCatalog');
 assert.equal(catalog.result?.ok,true,'Actual model-catalog RPC failed');
 const value=catalog.result.value;
 assert(value && value.default?.provider==='litellm-cluster','Actual catalog default differs');
 assert.deepEqual(value.routableProviders,['litellm-cluster'],'External provider appeared in actual catalog');
 const denied=await request('POST','/api/session/list','{}',false);
 assert([401,403].includes(denied.status),'Anonymous RPC was not denied');
 const wrongHost=await request('POST','/api/session/list','{}',true,'untrusted.invalid');
 assert([400,403,421].includes(wrongHost.status),'Untrusted Host was not denied');
 console.log(JSON.stringify({actualWebStartup:true,sessionList:true,internalModelCatalog:true,anonymousRpcDenied:true,untrustedHostDenied:true,disposableState:true,inferenceRequested:false}));
}finally{
 child.kill('SIGTERM');
 for(let n=0;n<20&&!closed;n++)await new Promise(r=>setTimeout(r,100));
 if(!closed)child.kill('SIGKILL');
 // This directory was created by this process; it contains synthetic state only.
 fs.rmSync(home,{recursive:true,force:true});
}})().catch(e=>{console.error(e.message);process.exitCode=1;});
