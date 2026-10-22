'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict');
const adapter=require('./runtime/gradio_alias');
const upstream='https://regchat.dev.apps.mlops.bot.or.th', alias='https://regchat.aiportal.bot.or.th';
const target=(patch={})=>({url:new URL(upstream),basePath:'',policy:{frontendAdapter:'regchat-gradio-root'},...patch});
const config={root:upstream,components:[{props:{value:'example </script> { [ " \\ \u2028 text'}}],dependencies:[{api_name:'chat',inputs:[1]}],nested:{root:upstream}};
function page(value=config){return '<!doctype html><script src="./assets/app.js"></script><script nonce="existing-nonce">window.gradio_config = '+JSON.stringify(value).replace(/</g,'\\u003c')+';</script><a href="'+upstream+'">original link</a>';}
function apply(value=page(),headers={'content-type':'text/html'},path='/'){return adapter.transform(Buffer.from(value),headers,path,target(),alias);}
test('only exact operator-selected origin and alias can enable the adapter',()=>{
 assert.equal(adapter.enabled(target({policy:{}}),alias),false);
 for(const [t,a]of [[target({url:new URL('https://evil.example')}),alias],[target(), 'https://other.aiportal.bot.or.th'],[target({basePath:'/private'}),alias],[target({policy:{frontendAdapter:'generic'}}),alias]])assert.throws(()=>adapter.enabled(t,a));
});
test('only successful GET root HTML or config JSON is eligible',()=>{
 for(const [method,path,status,type,want]of [['GET','/',200,'text/html; charset=utf-8',true],['GET','/config',200,'application/json',true],['GET','/?v=1',200,'text/html',true],['POST','/',200,'text/html',false],['GET','/assets/app.js',200,'text/javascript',false],['GET','/',302,'text/html',false],['GET','/',206,'text/html',false],['GET','/api/predict',200,'application/json',false]])assert.equal(adapter.eligible(target(),alias,method,path,status,{'content-type':type}),want);
});
test('changes only top-level config root; preserves values and surrounding HTML',()=>{
 const r=apply();const text=r.body.toString();const embedded=/window\.gradio_config = ([\s\S]*?);<\/script>/.exec(text)[1];
 assert.deepEqual(JSON.parse(embedded),{...config,root:alias});
 assert(text.includes('<a href="'+upstream+'">original link</a>'));
 assert(!embedded.includes('</script>'));assert(!embedded.includes('\u2028'));
 assert.equal(r.headers['content-length'],String(r.body.length));assert.equal(r.headers['cache-control'],'no-store');
});
test('config JSON changes only the same top-level root',()=>{const r=apply(JSON.stringify(config),{'content-type':'application/json'},'/config');assert.deepEqual(JSON.parse(r.body),{...config,root:alias});});
test('does not retain stale body validators and preserves security/auth headers',()=>{
 const h={'content-type':'text/html',etag:'old','content-length':'1','content-md5':'old',digest:'old','content-digest':'old','repr-digest':'old','accept-ranges':'bytes','last-modified':'old','set-cookie':['application_session=synthetic; Secure'],'content-security-policy':"script-src 'nonce-existing-nonce'"};
 const r=apply(page(),h);for(const k of ['etag','content-md5','digest','content-digest','repr-digest','accept-ranges','last-modified'])assert(!Object.hasOwn(r.headers,k));
 assert.equal(h.etag,'old');assert.deepEqual(r.headers['set-cookie'],h['set-cookie']);assert.equal(r.headers['content-security-policy'],h['content-security-policy']);
});
test('rejects wrong root, malformed JSON, missing/duplicate assignment or unsafe script syntax',()=>{
 for(const p of [page({...config,root:'https://evil.example'}),page({...config,root:upstream+'/unexpected'}),'<script>window.gradio_config = {root:1};</script>','<p>no configuration</p>',page()+page(),'<script>window.gradio_config = '+JSON.stringify(config)+' + {root:"evil"};</script>'])assert.throws(()=>apply(p));
});
test('rejects oversized bodies, invalid UTF-8, compression and hashed script policies',()=>{
 assert.throws(()=>adapter.transform(Buffer.alloc(adapter.MAX_BYTES+1),{},'/',target(),alias));
 assert.throws(()=>adapter.transform(Buffer.from([0xff]),{},'/',target(),alias));
 for(const h of [{'content-encoding':'gzip'},{'content-encoding':'br'},{'content-security-policy':"script-src 'sha256-abc'"},{'content-security-policy-report-only':"script-src 'sha512-abc'"}])assert.throws(()=>apply(page(),h));
});
test('Suprisk remains unchanged with no adapter policy',()=>{
 const t=target({url:new URL('https://suprisk.test.apps.mlops.bot.or.th'),policy:{}});
 assert.equal(adapter.eligible(t,'https://suprisk.aiportal.bot.or.th','GET','/',302,{'content-type':'text/html'}),false);
});
