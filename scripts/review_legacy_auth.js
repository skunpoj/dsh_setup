// Run inside one legacy instance; never print stored passwords or response bodies.
const fs=require('fs'),http=require('http'),assert=require('assert');
const users=JSON.parse(fs.readFileSync('/workspace/users/.user_auth.json'));
if(Object.values(users).some(v=>typeof v!=='string'))throw new Error('Stored hashes are not login credentials; supply approved test credentials privately through the rollout verifier.');
const activeStore=JSON.parse(fs.readFileSync(process.env.DSH_USER_STORE_PATH||'/workspace/users/.user_auth.json'));
const user=process.env.AUTH_USER,host=process.env.DSH_TRUSTED_HOST;
const request=(method,path,body='',cookie='',type='application/x-www-form-urlencoded')=>new Promise((resolve,reject)=>{
 const r=http.request({hostname:'127.0.0.1',port:3080,path,method,headers:{host,cookie,
  'content-type':type,'content-length':Buffer.byteLength(body)}},s=>{
  let text='';s.on('data',b=>text+=b);s.on('end',()=>resolve({status:s.statusCode,text,
   cookie:(s.headers['set-cookie']||[]).map(x=>x.split(';')[0]).join('; ')}));
 });r.setTimeout(15000,()=>r.destroy(new Error('timeout')));r.on('error',reject);r.end(body);
});
const loginPage=r=>/type\s*=\s*["']password["']/i.test(r.text)&&/login|เข้าสู่ระบบ/i.test(r.text);
const rpcBody=JSON.stringify({type:'client-request',rpcId:'legacy-auth-review',method:'session/list',payload:{args:{_request:{}}}});
(async()=>{
 const anon=await request('GET','/');
 const history=await request('POST','/api/session/list',rpcBody,'','application/json');
 const registration=await request('GET','/register');
 const login=await request('POST','/login',new URLSearchParams({username:user,password:users[user]}).toString());
 assert.equal(login.status,302);
 let peerLoginsDenied=0;
 for(const other of Object.keys(users).filter(n=>n!==user)){const r=await request('POST','/login',new URLSearchParams({username:other,password:users[other]}).toString());assert.equal(r.status,401);peerLoginsDenied++;}
 try{
  const app=await request('GET','/','',login.cookie);
  const list=await request('POST','/api/session/list',rpcBody,login.cookie,'application/json');
  let parsed;try{parsed=JSON.parse(list.text);}catch{}
  await request('GET','/logout','',login.cookie);
  const revoked=await request('GET','/','',login.cookie);
  console.log(JSON.stringify({anonymousAppStatus:anon.status,anonymousAppIsLoginPage:loginPage(anon),
   anonymousHistoryStatus:history.status,anonymousHistoryIsLoginPage:loginPage(history),
   registrationPageStatus:registration.status,registrationIsLoginPage:loginPage(registration),
   sharedGuestAccountPresent:Object.hasOwn(activeStore,'guest'),accountsInSharedRuntime:Object.keys(activeStore).length,
   designatedLoginSucceeded:true,peerLoginsDenied,authenticatedAppIsLoginPage:loginPage(app),
   authenticatedHistoryRpcSucceeded:parsed?.result?.ok===true,
   authenticatedHistoryCount:parsed?.result?.value?.items?.length??null,
   revokedCookieIsLoginPage:loginPage(revoked)}));
 }finally{await request('GET','/logout','',login.cookie);}
})().catch(e=>{console.error(e.message);process.exitCode=1;});
