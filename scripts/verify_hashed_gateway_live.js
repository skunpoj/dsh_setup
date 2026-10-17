// Execute inside the gateway. The unmapped synthetic identity never gets a runtime.
const fs=require('fs'),crypto=require('crypto'),http=require('http'),assert=require('assert');
const {hashPassword,verifyPassword,writeAtomicUsers}=require('/gateway-source/password_store');
const file=process.env.DSH_USER_STORE_PATH,user='hashcheck_'+crypto.randomBytes(6).toString('hex');
const password=crypto.randomBytes(24).toString('hex'),next=crypto.randomBytes(24).toString('hex');
const read=()=>JSON.parse(fs.readFileSync(file));
const request=(path,body)=>new Promise((resolve,reject)=>{
 const req=http.request({host:'127.0.0.1',port:3080,path,method:'POST',headers:{host:'dsh.aiportal.bot.or.th','content-type':'application/x-www-form-urlencoded','content-length':Buffer.byteLength(body)}},res=>{res.resume();res.on('end',()=>resolve(res.statusCode));});
 req.setTimeout(15000,()=>req.destroy(new Error('Verification timeout')));req.on('error',reject);req.end(body);
});
(async()=>{
 const initial=read(),count=Object.keys(initial).length;assert(!Object.hasOwn(initial,user));initial[user]=hashPassword(password);writeAtomicUsers(file,initial);
 try {
  const login=p=>request('/login',new URLSearchParams({username:user,password:p}).toString());
  assert.equal(await login('wrong'),401);
  assert.equal(await login(password),403); // Password accepted; no provisioned route.
  assert.equal(await request('/change-password',new URLSearchParams({username:user,old_password:password,new_password:'x'.repeat(1025)}).toString()),400);
  assert.equal(await request('/login','x'.repeat(17000)),413);
  assert.equal(await request('/change-password',new URLSearchParams({username:user,old_password:password,new_password:next}).toString()),200);
  assert.equal(await login(password),401);assert.equal(await login(next),403);
  assert(await verifyPassword(next,read()[user]));
  console.log(JSON.stringify({wrongPasswordDenied:true,unmappedRuntimeDenied:true,passwordChangePersisted:true,oversizedPasswordDenied:true,oversizedFormDenied:true,syntheticIdentityReceivedRuntime:false}));
 } finally {
  const current=read();assert(current[user]?.scheme==='scrypt-v1');delete current[user];writeAtomicUsers(file,current);
  assert.equal(Object.keys(read()).length,count);
 }
})().catch(e=>{console.error(e.message);process.exitCode=1;});
