// Runs privately in the gateway. Never prints account names, tokens or histories.
const fs=require('fs'),http=require('http'),crypto=require('crypto'),assert=require('assert');
const users=JSON.parse(fs.readFileSync(process.env.DSH_USER_STORE_PATH,'utf8'));
const routes=JSON.parse(fs.readFileSync(process.env.DSH_USER_TARGETS_FILE,'utf8'));
const request=(method,path,body='',cookie='',extra={})=>new Promise((resolve,reject)=>{
 const req=http.request({host:'127.0.0.1',port:3080,path,method,headers:{host:'dsh.aiportal.bot.or.th',cookie,
  'content-type':'application/json','content-length':Buffer.byteLength(body),...extra}},res=>{
  let text='';res.on('data',b=>text+=b);res.on('end',()=>resolve({status:res.statusCode,text,
  cookie:(res.headers['set-cookie']||[]).map(s=>s.split(';')[0]).join('; ')}));});
 req.setTimeout(20000,()=>req.destroy(new Error('Private routing request timeout')));req.on('error',reject);req.end(body);
});
const rpc=async(cookie,method,args)=>JSON.parse((await request('POST','/api/'+method,
 JSON.stringify({type:'client-request',rpcId:crypto.randomUUID(),method,payload:{args}}),cookie)).text);
(async()=>{
 const result={timeUTC:new Date().toISOString(),adminLegacyCount:0,privateLogins:0,privateEmptyHistories:0,
  legacyPageDenials:0,ordinaryAdminDenials:0,excludedAccountDenials:0,auditEventsVisible:false};
 const cookies=[];let example;
 try{
  // Admin's existing legacy tree remains in place; no session is created here.
  for(const user of ['admin',...Object.keys(routes).filter(u=>u!=='admin')]){
   for(const mode of ['off','on']){
    const response=await request('POST','/login',new URLSearchParams({username:user,password:users[user],internet:mode}).toString(),'',{'content-type':'application/x-www-form-urlencoded'});
    assert.equal(response.status,302);const cookie=response.cookie;cookies.push(cookie);
    const list=await rpc(cookie,'session/list',{_request:{}});assert.equal(list.result?.ok,true);
    const items=list.result.value.items;
    if(user==='admin'&&mode==='off'){
     assert.equal(items.length,80);result.adminLegacyCount=items.length;example=items[0];
    }else if(user!=='admin'){
     result.privateLogins++;assert(!items.some(item=>item.sessionId===example.sessionId));if(items.length===0)result.privateEmptyHistories++;
     const denied=await rpc(cookie,'session/page',{request:{address:{kind:'session',sessionId:example.sessionId},throughSeq:1,maxMessages:1}});
     assert.equal(denied.result?.ok,false);assert(/not.found|no persisted session/i.test(JSON.stringify(denied.result.error)));result.legacyPageDenials++;
     assert.equal((await request('GET','/api/admin/summary','',cookie,{'x-dsh-user':'admin'})).status,403);result.ordinaryAdminDenials++;
    }
    const terminal=await request('GET','/terminal','',cookie);assert.equal(terminal.status,302);
    const page=await request('GET','/proxy/7681/','',cookie);assert.equal(page.status,200);assert(/ttyd|terminal/i.test(page.text));
    if(user==='admin'&&mode==='off'){
     const summary=JSON.parse((await request('GET','/api/admin/summary','',cookie)).text);
     assert.equal(summary.privateUserRouting,true);
     assert.deepEqual(summary.snapshot,JSON.parse(fs.readFileSync('/admin-status/summary.json','utf8')));
     result.adminSnapshotContentVerified=true;
     const audit=JSON.parse((await request('GET','/api/admin/audit','',cookie)).text);
     assert(audit.events.length>0);assert(audit.events.every(e=>Object.keys(e).sort().join(',')==='environment,event,time,user'));result.auditEventsVisible=true;
    }
   }
  }
  for(const user of Object.keys(users).filter(u=>!Object.hasOwn(routes,u))){
   const r=await request('POST','/login',new URLSearchParams({username:user,password:users[user],internet:'off'}).toString(),'',{'content-type':'application/x-www-form-urlencoded'});
   assert.equal(r.status,403);result.excludedAccountDenials++;
  }
  console.log(JSON.stringify(result));
 }finally{for(const cookie of cookies)await request('GET','/logout','',cookie);}
})().catch(e=>{console.error(e.message);process.exitCode=1;});
