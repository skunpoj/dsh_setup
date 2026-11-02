const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path'),http=require('node:http'),crypto=require('node:crypto');
const {spawn}=require('node:child_process');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-manual-')),dir=path.join(root,'manual'),port=39741;
fs.mkdirSync(dir);fs.writeFileSync(path.join(root,'users.json'),'{}');
const body='<html><body>Public operator-published manual</body></html>';
const media=Buffer.from(Array.from({length:512},(_,i)=>i%256)),captions='WEBVTT\n\n00:00.000 --> 00:01.000\nFixture\n';
fs.writeFileSync(path.join(dir,'guide.html'),body);
fs.mkdirSync(path.join(dir,'media'));fs.writeFileSync(path.join(dir,'media','guide.mp4'),media);fs.writeFileSync(path.join(dir,'media','guide.vtt'),captions);
fs.writeFileSync(path.join(root,'private.json'),'PRIVATE_ACCOUNT_CONTENT');
const entry={bytes:Buffer.byteLength(body),sha256:crypto.createHash('sha256').update(body).digest('hex')},mediaEntry={bytes:media.length,sha256:crypto.createHash('sha256').update(media).digest('hex')},captionEntry={bytes:Buffer.byteLength(captions),sha256:crypto.createHash('sha256').update(captions).digest('hex')};
fs.writeFileSync(path.join(dir,'tampered.html'),body+'changed');
fs.writeFileSync(path.join(dir,'manifest.json'),JSON.stringify({files:{'guide.html':entry,'tampered.html':entry,'media/guide.mp4':mediaEntry,'media/guide.vtt':captionEntry}}));
const request=(route,method='GET',headers={})=>new Promise((resolve,reject)=>{const r=http.request({hostname:'127.0.0.1',port,path:route,method,headers},res=>{const chunks=[];res.on('data',b=>chunks.push(b));res.on('end',()=>{const bytes=Buffer.concat(chunks);resolve({status:res.statusCode,text:bytes.toString(),bytes,headers:res.headers})});});r.on('error',reject);r.end();});
const child=spawn(process.execPath,[path.join(__dirname,'../scripts/auth_proxy.js')],{env:{...process.env,PORT:String(port),DSH_MANUAL_DIR:dir,DSH_USER_STORE_PATH:path.join(root,'users.json'),WORKSPACE_ROOT:root},stdio:'ignore'});
(async()=>{try{
 let ready=false;for(let i=0;i<60;i++){try{await request('/manual');ready=true;break;}catch{await new Promise(r=>setTimeout(r,50));}}assert(ready);
 const redirect=await request('/manual/');assert.equal(redirect.status,302);assert.equal(redirect.headers.location,'/manual/index.html');
 const page=await request('/manual/guide.html');assert.equal(page.status,200);assert.equal(page.text,body);assert.equal(page.headers['x-content-type-options'],'nosniff');
 const video=await request('/manual/media/guide.mp4');assert.equal(video.status,200);assert.deepEqual(video.bytes,media);assert.equal(video.headers['content-type'],'video/mp4');assert.equal(video.headers['accept-ranges'],'bytes');
 const range=await request('/manual/media/guide.mp4','GET',{Range:'bytes=16-31'});assert.equal(range.status,206);assert.deepEqual(range.bytes,media.subarray(16,32));assert.equal(range.headers['content-range'],'bytes 16-31/512');
 const vtt=await request('/manual/media/guide.vtt');assert.equal(vtt.status,200);assert.equal(vtt.text,captions);assert.equal(vtt.headers['content-type'],'text/vtt; charset=utf-8');
 assert.equal((await request('/manual/guide.html','HEAD')).text,'');
 assert.equal((await request('/manual/guide.html','POST')).status,405);
 for(const route of ['/manual/%2e%2e/private.json','/manual/%2f../private.json','/manual/private.json','/manual/tampered.html','/manual/manifest.json']){const r=await request(route);assert.equal(r.status,404,route);assert(!r.text.includes('PRIVATE_ACCOUNT_CONTENT'));}
 console.log('Public manual allowlist, integrity, traversal and method checks passed');
}finally{child.kill();await new Promise(r=>child.once('exit',r));fs.rmSync(root,{recursive:true,force:true});}})().catch(e=>{console.error(e);process.exitCode=1;});
