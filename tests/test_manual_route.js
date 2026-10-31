const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),http=require('node:http'),crypto=require('node:crypto');
const {spawn}=require('node:child_process');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-manual-')),dir=path.join(root,'manual'),port=39741;
fs.mkdirSync(dir);fs.writeFileSync(path.join(root,'users.json'),'{}');
const body='<html><body>Public operator-published manual</body></html>';
fs.writeFileSync(path.join(dir,'guide.html'),body);
fs.writeFileSync(path.join(root,'private.json'),'PRIVATE_ACCOUNT_CONTENT');
const entry={bytes:Buffer.byteLength(body),sha256:crypto.createHash('sha256').update(body).digest('hex')};
fs.writeFileSync(path.join(dir,'tampered.html'),body+'changed');
fs.writeFileSync(path.join(dir,'manifest.json'),JSON.stringify({files:{'guide.html':entry,'tampered.html':entry}}));
const request=(route,method='GET')=>new Promise((resolve,reject)=>{const r=http.request({hostname:'127.0.0.1',port,path:route,method},res=>{let text='';res.on('data',b=>text+=b);res.on('end',()=>resolve({status:res.statusCode,text,headers:res.headers}));});r.on('error',reject);r.end();});
const child=spawn(process.execPath,[path.join(__dirname,'../scripts/auth_proxy.js')],{env:{...process.env,PORT:String(port),DSH_MANUAL_DIR:dir,DSH_USER_STORE_PATH:path.join(root,'users.json'),WORKSPACE_ROOT:root},stdio:'ignore'});
(async()=>{try{
 let ready=false;for(let i=0;i<60;i++){try{await request('/manual');ready=true;break;}catch{await new Promise(r=>setTimeout(r,50));}}assert(ready);
 const redirect=await request('/manual/');assert.equal(redirect.status,302);assert.equal(redirect.headers.location,'/manual/DSH_USER_MANUAL.html');
 const page=await request('/manual/guide.html');assert.equal(page.status,200);assert.equal(page.text,body);assert.equal(page.headers['x-content-type-options'],'nosniff');
 assert.equal((await request('/manual/guide.html','HEAD')).text,'');
 assert.equal((await request('/manual/guide.html','POST')).status,405);
 for(const route of ['/manual/%2e%2e/private.json','/manual/%2f../private.json','/manual/private.json','/manual/tampered.html','/manual/manifest.json']){const r=await request(route);assert.equal(r.status,404,route);assert(!r.text.includes('PRIVATE_ACCOUNT_CONTENT'));}
 console.log('Public manual allowlist, integrity, traversal and method checks passed');
}finally{child.kill();await new Promise(r=>child.once('exit',r));fs.rmSync(root,{recursive:true,force:true});}})().catch(e=>{console.error(e);process.exitCode=1;});
