'use strict';
const fs=require('fs'),https=require('https'),crypto=require('crypto');
const creds=JSON.parse(fs.readFileSync('/test-credentials/target.json','utf8'));
const token=crypto.createHash('sha256').update(creds.password+'app-target').digest('hex');
const reference=process.env.TEST_SOURCE_REVISION;
if(!/^app-focused-login-[a-f0-9]{8}$/.test(reference||''))throw Error('Missing Test source revision');
const protectedCookie=name=>['dsh_auth','dsh2_auth','dsh3_auth'].includes(name)||name.startsWith('dsh-auth-');
const authenticated=req=>String(req.headers.cookie||'').split(';').some(x=>x.trim()==='test_app_session='+token);
https.createServer({key:fs.readFileSync('/test-tls/tls.key'),cert:fs.readFileSync('/test-tls/tls.crt')},(req,res)=>{
 const origin='https://'+process.env.TEST_UPSTREAM_HOST+':9443';
 if(req.url==='/base/login'&&req.method==='POST'){
  let body='',large=false;req.on('data',b=>{if(large)return;body+=b;if(Buffer.byteLength(body)>4096){large=true;res.writeHead(413);res.end('Form too large');}});
  req.on('end',()=>{if(large)return;const f=new URLSearchParams(body);if(f.get('username')!==creds.username||f.get('password')!==creds.password){res.writeHead(403);return res.end('Application sign-in denied');}res.writeHead(303,{Location:origin+'/base/private','Set-Cookie':'test_app_session='+token+'; Path=/base; Secure; HttpOnly; SameSite=Lax'});res.end();});return;
 }
 if(req.url==='/base/private'){
  if(!authenticated(req)){res.writeHead(401);return res.end('Demonstration application sign-in required');}
  res.setHeader('Content-Type','application/json');return res.end(JSON.stringify({application:'Isolated DSH app-sign-in demonstration',source_reference:reference,authenticated:true,received_dsh_cookie:String(req.headers.cookie||'').split(';').some(x=>protectedCookie(x.trim().split('=')[0])),received_authorization:Boolean(req.headers.authorization)}));
 }
 if(req.url==='/base/logout'){res.setHeader('Set-Cookie','test_app_session=; Path=/base; Max-Age=0; Secure; SameSite=Lax');return res.end('Demonstration application signed out');}
 res.setHeader('Content-Type','text/html; charset=utf-8');res.end('<!doctype html><meta name="viewport" content="width=device-width"><title>Demonstration application</title><h1>Demonstration application sign-in</h1><p>This is the destination application, separate from the Test DSH access check.</p><form method="post" action="/login"><label>Application username<input name="username" autocomplete="username"></label><label>Application password<input name="password" type="password" autocomplete="current-password"></label><button>Open demonstration content</button></form>');
}).on('upgrade',(req,socket)=>{
 if(!authenticated(req)){socket.end('HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n');return;}
 const accept=crypto.createHash('sha1').update(req.headers['sec-websocket-key']+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
 socket.write('HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: '+accept+'\r\n\r\n');
 socket.on('data',b=>{if(b.length<6||!(b[1]&128)||(b[1]&127)>125)return socket.destroy();const n=b[1]&127;if(b.length<n+6)return socket.destroy();const data=Buffer.from(b.subarray(6,6+n));for(let i=0;i<n;i++)data[i]^=b[2+i%4];socket.write(Buffer.concat([Buffer.from([0x81,n]),data]));});socket.on('error',()=>socket.destroy());
}).listen(9443,'0.0.0.0');
