// Execute privately inside the gateway. Credentials/cookies never leave it.
const fs=require('fs'),http=require('http'),assert=require('assert');
const users=JSON.parse(fs.readFileSync(process.env.DSH_USER_STORE_PATH,'utf8'));
const admin=(process.env.DSH_ADMIN_USERS||'admin').split(',').map(s=>s.trim()).find(s=>Object.hasOwn(users,s));
const ordinary=JSON.parse(fs.readFileSync('/auth/.runtime-rollout-probe.json','utf8'));
const request=(method,path,body='',cookie='',extra={})=>new Promise((resolve,reject)=>{
 const req=http.request({host:'127.0.0.1',port:3080,path,method,headers:{host:'dsh.aiportal.bot.or.th',cookie,
 'content-type':'application/x-www-form-urlencoded','content-length':Buffer.byteLength(body),...extra}},res=>{
 let text='';res.on('data',b=>text+=b);res.on('end',()=>resolve({status:res.statusCode,text,
 cookie:(res.headers['set-cookie']||[]).map(s=>s.split(';')[0]).join('; '),headers:res.headers}));});
 req.setTimeout(15000,()=>req.destroy(new Error('Dashboard verification timeout')));req.on('error',reject);req.end(body);
});
(async()=>{
 assert(admin,'No provisioned admin identity');let adminCookie='',userCookie='';
 try{
  const login=async(user,password)=>{const r=await request('POST','/login',new URLSearchParams({username:user,password,internet:'off'}).toString());assert.equal(r.status,302);return r.cookie;};
  adminCookie=await login(admin,users[admin]);userCookie=await login(ordinary.user,ordinary.password);
  const page=await request('GET','/admin','',adminCookie);assert.equal(page.status,200);assert(page.text.includes('DSH Admin overview'));
  const api=await request('GET','/api/admin/summary','',adminCookie);assert.equal(api.status,200);const summary=JSON.parse(api.text);
  const saved=JSON.parse(fs.readFileSync('/admin-status/summary.json','utf8'));
  assert.equal(summary.snapshot.observedAt,saved.observedAt);assert.equal(summary.snapshot.model.userContext,saved.model.userContext);
  assert.equal(summary.snapshot.environments.length,4);assert.equal(summary.privateUserRouting,false);
  assert.equal(api.headers['cache-control'],'no-store');
  assert.equal((await request('GET','/api/admin/summary','',userCookie,{'x-dsh-user':admin,'x-dsh-role':'admin'})).status,403);
  assert.equal((await request('GET','/admin','',userCookie)).status,403);
  assert((await request('GET','/api/admin/summary')).text.includes('id="pane-login"'));
  assert((await request('GET','/','',adminCookie)).text.includes('id="dsh-admin-dashboard"'));
  assert(!(await request('GET','/','',userCookie)).text.includes('id="dsh-admin-dashboard"'));
  console.log(JSON.stringify({passed:true,timeUTC:new Date().toISOString(),adminPage:true,adminSummary:true,
   snapshotMatchesMountedContent:true,snapshotObservedAt:summary.snapshot.observedAt,environmentCount:4,
   ordinaryUserDenied:true,forgedRoleDenied:true,anonymousDenied:true,adminOnlyNavigation:true,
   passwordsOrCookiesExported:false}));
 }finally{
  if(adminCookie)await request('GET','/logout','',adminCookie);
  if(userCookie)await request('GET','/logout','',userCookie);
 }
})().catch(e=>{console.error(e.message);process.exitCode=1;});
