import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const root=path.resolve(import.meta.dirname,'..'),docs=path.join(root,'docs');
const modules=process.env.DSH_DOC_NODE_MODULES||path.join(root,'node_modules');
const {marked}=await import(pathToFileURL(path.join(modules,'marked/lib/marked.esm.js')));
const read=name=>fs.readFileSync(path.join(docs,name),'utf8');
const image=name=>'data:image/png;base64,'+fs.readFileSync(path.join(docs,'images/platform',name)).toString('base64');
const clip='data:video/webm;base64,'+fs.readFileSync(path.join(docs,'videos/signup-capacity.webm')).toString('base64');
const css='*{box-sizing:border-box}body{font:17px/1.65 system-ui;margin:0;background:#edf2f7;color:#193047}main{max-width:1100px;margin:auto;padding:28px}a{color:#0369a1}h1,h2,h3{line-height:1.3}h2{margin-top:38px}table{border-collapse:collapse;width:100%;table-layout:fixed}td,th{padding:12px;text-align:left;border-bottom:1px solid #bdcbd8;overflow-wrap:anywhere}img,video{width:100%;max-width:100%;height:auto;background:white;border-radius:12px}pre{white-space:pre-wrap;overflow-wrap:anywhere}code{overflow-wrap:anywhere}figure{margin:20px 0}figcaption{font-size:14px;color:#475569}nav{display:flex;gap:18px;flex-wrap:wrap}@media(max-width:600px){main{padding:16px}body{font-size:16px}td,th{padding:8px}}';
const navigation='<nav><a href="DSH_USER_MANUAL.html">User manual</a><a href="DSH_GUIDED_TOUR.html">Guided tour</a><a href="ADMIN_USAGE_TELEMETRY.html">Admin guide</a></nav>';
function page(title,body){return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+title+'</title><style>'+css+'</style></head><body><main>'+navigation+body+'</main></body></html>';}
let prose=read('PLATFORM_CAPACITY_AND_CLIENTS.md').replace('(SHARED_PLATFORM_GUIDE.md)','(SHARED_PLATFORM_GUIDE.html)');
prose=marked.parse(prose);
const media='<h2>Watch capacity update</h2><p>Create account shows the remaining new-user slots and refreshes as accounts are assigned. The admin view separates prepared capacity from active usage.</p><video controls preload="metadata" playsinline poster="'+image('signup-capacity.png')+'" src="'+clip+'" aria-label="Signup capacity changes and admin capacity overview"></video><ol><li>Open Create account and read the current new-user slot count.</li><li>Two demonstration accounts are created; the visible count changes from two to one to zero.</li><li>A refresh failure replaces the number with an unavailable message, then recovers.</li><li>Admin overview shows both assigned slots and the account counts.</li></ol><figure><img src="'+image('admin-capacity.png')+'" alt="Admin capacity view with three demonstration accounts and two assigned slots"><figcaption>Demonstration accounts: one admin and two newly assigned users. The counts shown are examples.</figcaption></figure>';
fs.writeFileSync(path.join(docs,'PLATFORM_CAPACITY_AND_CLIENTS.html'),page('DSH — Capacity, monitoring and client guidance',prose+media));
const instructions=read('SHARED_PLATFORM_GUIDE.md').replace('(../container/PLATFORM_GUIDE.md)','(https://github.com/skunpoj/dsh_setup/blob/main/container/PLATFORM_GUIDE.md)');
fs.writeFileSync(path.join(docs,'SHARED_PLATFORM_GUIDE.html'),page('DSH — Shared client platform guide',marked.parse(instructions)));
console.log(JSON.stringify({pages:2,embeddedCapacityVideo:true}));
