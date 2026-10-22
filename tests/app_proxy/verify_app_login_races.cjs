'use strict';
// Local synthetic fault injection around the real asynchronous password verifier.
// No cluster, browser, production identity, or external network access is used.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),cp=require('node:child_process'),crypto=require('node:crypto');
const runtime=path.resolve(process.argv[2]||path.join(__dirname,'../../scripts'));
const stamp=Date.now(), root=path.join(path.resolve(process.argv[3]||require('node:os').tmpdir()),'race-'+stamp);fs.mkdirSync(root,{recursive:true,mode:0o700});
const hashes=Object.fromEntries(fs.readdirSync(runtime).filter(n=>n.endsWith('.js')).map(n=>[n,crypto.createHash('sha256').update(fs.readFileSync(path.join(runtime,n))).digest('hex')]));
const {hashPassword}=require(path.join(runtime,'password_store.js'));
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function waitFile(p){for(let i=0;i<150;i++){if(fs.existsSync(p))return;await delay(20);}throw Error('marker timeout');}
function req(port,url,opts={}){return new Promise(resolve=>{const body=opts.body||'';const r=http.request({host:'127.0.0.1',port,path:url,method:opts.method||'GET',headers:{Host:'gateway.review.invalid',Origin:'https://gateway.review.invalid',...(opts.cookie?{Cookie:opts.cookie}:{}),...(body?{'Content-Type':'application/x-www-form-urlencoded','Content-Length':Buffer.byteLength(body)}:{})}},s=>{let text='';s.on('data',b=>text+=b);s.on('end',()=>resolve({status:s.statusCode,headers:s.headers,text}));});r.on('error',e=>resolve({error:e.code}));r.setTimeout(5000,()=>r.destroy(Error('timeout')));r.end(body);});}
async function run(correct,full=false){
 const dir=path.join(root,full?'full-capacity':correct?'correct-password':'wrong-password');fs.mkdirSync(dir,{mode:0o700});
 const marker=path.join(dir,'verified.marker'),release=path.join(dir,'release.marker');
 const preload=path.join(dir,'hold-verifier.cjs');
 fs.writeFileSync(preload,`const fs=require('node:fs'),p=require(${JSON.stringify(path.join(runtime,'password_store.js'))}),verify=p.verifyPassword;p.verifyPassword=async(...args)=>{const result=await verify(...args);fs.writeFileSync(${JSON.stringify(marker)},'verified');await new Promise((resolve,reject)=>{const t=setInterval(()=>{if(fs.existsSync(${JSON.stringify(release)})){clearInterval(t);clearTimeout(deadline);resolve();}},10);const deadline=setTimeout(()=>{clearInterval(t);reject(Error('Review gate timeout'));},5000);});return result;};`);
 if(full)fs.appendFileSync(preload,`const modulePath=${JSON.stringify(path.join(runtime,'app_signin.js'))},Original=require(modulePath).AppSignIn;require(modulePath).AppSignIn=class extends Original{constructor(o){super({...o,limit:2});}};`);
 const links=path.join(dir,'app-links.json');
 fs.writeFileSync(path.join(dir,'users.json'),JSON.stringify({alice:hashPassword('synthetic-review-password')}));
 fs.writeFileSync(path.join(dir,'routes.json'),JSON.stringify({alice:{secure:{host:'127.0.0.1',port:39999,tokenFile:'/runtime-tokens/review-only-no-runtime'}}}));
 fs.writeFileSync(links,JSON.stringify({demo:{owner:'alice',ports:{off:8501},accessMode:'authenticated'}}));
 const probe=http.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));
 const env={PATH:process.env.PATH,SystemRoot:process.env.SystemRoot,HOME:dir,PORT:String(port),DSH_LISTEN_HOST:'127.0.0.1',WORKSPACE_ROOT:dir,DSH_USER_STORE_PATH:path.join(dir,'users.json'),DSH_USER_SETTINGS_PATH:path.join(dir,'settings.json'),DSH_USER_TARGETS_FILE:path.join(dir,'routes.json'),DSH_SESSION_STORE_PATH:path.join(dir,'sessions.json'),DSH_AUDIT_DIR:path.join(dir,'audit'),DSH_APP_LINKS_PATH:links,DSH_APP_DOMAIN:'review.invalid',DSH_TRUSTED_HOST:'gateway.review.invalid',DSH_ALLOW_REGISTRATION:'false',DSH_COOKIE_NAME:'review_only_auth',DSH_COOKIE_SECURE:'true',DSH_APP_LOGIN_ENABLED:'true'};
 const child=cp.spawn(process.execPath,['--require',preload,path.join(runtime,'auth_proxy.js')],{env,stdio:['ignore','pipe','pipe']});let log='';child.stdout.on('data',b=>log+=b);child.stderr.on('data',b=>log+=b);
 try{
  let form;for(let i=0;i<100;i++){form=await req(port,'/login?app=demo');if(form.status===200)break;if(child.exitCode!==null)throw Error(log);await delay(30);}if(form.status!==200)throw Error('startup failed');
  const token=form.text.match(/name="app_login" value="([a-f0-9]+)"/)[1],cookie=form.headers['set-cookie'][0].split(';')[0];
  const pending=req(port,'/login',{method:'POST',cookie,body:new URLSearchParams({app_login:token,username:'alice',password:correct?'synthetic-review-password':'wrong-review-password'}).toString()});
  await waitFile(marker);let capacityForms=[];if(full){capacityForms=[await req(port,'/login?app=demo'),await req(port,'/login?app=demo')];if(capacityForms.some(x=>x.status!==200))throw Error('capacity preparation failed');}else fs.writeFileSync(links,'{}');fs.writeFileSync(release,'continue');
  const response=await pending;await delay(100);const sessionFile=path.join(dir,'sessions.json'),persisted=fs.existsSync(sessionFile)?JSON.parse(fs.readFileSync(sessionFile,'utf8')):{};
  const rejectedSessionPersisted=JSON.stringify(persisted).includes('"user":"alice"');
  const followup=await req(port,'/login');let subsequentValidStatus;if(full){const form=capacityForms[0],token=form.text.match(/name="app_login" value="([a-f0-9]+)"/)[1],cookie=form.headers['set-cookie'][0].split(';')[0];const valid=await req(port,'/login',{method:'POST',cookie,body:new URLSearchParams({app_login:token,username:'alice',password:'synthetic-review-password'}).toString()});subsequentValidStatus=valid.status;}
  return{case:full?'pending capacity filled during wrong-password verification':correct?'mapping removed during correct-password verification':'mapping removed during wrong-password verification',response:{status:response.status,error:response.error,location:response.headers?.location,session_cookie_created:Boolean(response.headers?.['set-cookie']?.some(x=>x.startsWith('review_only_auth=')))},gateway_alive:child.exitCode===null,rejected_session_persisted:rejectedSessionPersisted,following_login_status:followup.status,subsequent_valid_login_status:subsequentValidStatus,pass:(full?response.status===503:response.status===403)&&!rejectedSessionPersisted&&!response.headers?.['set-cookie']?.some(x=>x.startsWith('review_only_auth='))&&child.exitCode===null&&followup.status===200&&(!full||subsequentValidStatus===303)};
 }finally{if(child.exitCode===null&&child.signalCode===null){const exited=new Promise(r=>child.once('exit',r));child.kill();await exited;}fs.writeFileSync(path.join(dir,'gateway.log'),log);}
}
(async()=>{const cases=[await run(false),await run(true),await run(false,true)],report={observed_at:new Date().toISOString(),runtime,hashes,scope:'Local synthetic accounts and held real password verifier; no production or external calls',cases,pass:cases.every(x=>x.pass)};fs.writeFileSync(path.join(root,'RESULT.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({result_path:path.join(root,'RESULT.json'),...report}));if(!report.pass)process.exitCode=1;})().catch(e=>{console.error(e);process.exitCode=1;});
