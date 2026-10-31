// The sign-in page's "User manual" link floats on wide screens but sits below the card on phones,
// where a fixed button used to cover form fields. Real gateway process and Edge.
const assert=require('assert/strict'),fs=require('fs'),os=require('os'),path=require('path'),http=require('http');
const {spawn}=require('child_process');
const root=fs.mkdtempSync(path.join(os.tmpdir(),'dsh-manual-link-'));
const port=39670;
let gateway;
const get=route=>new Promise((resolve,reject)=>http.get({host:'127.0.0.1',port,path:route},res=>{res.resume();res.on('end',()=>resolve(res.statusCode));}).on('error',reject));
(async()=>{try{
 fs.writeFileSync(path.join(root,'users.json'),JSON.stringify({admin:'synthetic-admin'}));
 fs.writeFileSync(path.join(root,'summary.json'),JSON.stringify({observedAt:new Date().toISOString(),environments:[],model:{},performance:[],gaps:[]}));
 fs.writeFileSync(path.join(root,'targets.json'),JSON.stringify({admin:{secure:{host:'127.0.0.1',port:39671,tokenFile:'/runtime-tokens/synthetic'},internet:{host:'127.0.0.1',port:39671,tokenFile:'/runtime-tokens/synthetic'}}}));
 gateway=spawn(process.execPath,[path.join(__dirname,'../scripts/auth_proxy.js')],{env:{...process.env,PORT:String(port),WORKSPACE_ROOT:root,DSH_USER_STORE_PATH:path.join(root,'users.json'),DSH_USER_SETTINGS_PATH:path.join(root,'settings.json'),DSH_USER_TARGETS_FILE:path.join(root,'targets.json'),DSH_ADMIN_SUMMARY_FILE:path.join(root,'summary.json'),DSH_AUDIT_DIR:path.join(root,'audit'),DSH_COOKIE_SECURE:'false',DSH_TRUSTED_HOST:'127.0.0.1:'+port},stdio:'ignore'});
 let up=false;for(let i=0;i<80&&!up;i++){try{await get('/login');up=true;}catch{await new Promise(r=>setTimeout(r,50));}}
 assert(up,'Gateway did not start');
 const {chromium}=require(process.env.DSH_PLAYWRIGHT||'playwright');
 const browser=await chromium.launch({headless:true,...(process.platform==='win32'?{executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'}:{})});
 try{
  for(const [label,width,height] of [['desktop',1440,1000],['tablet',760,1000],['phone',390,844]]){
   const page=await browser.newPage({viewport:{width,height}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
   await page.goto('http://127.0.0.1:'+port+'/login');
   const r=await page.evaluate(()=>{
    const fab=document.querySelector('.manual-fab'),card=document.querySelector('.login-card'),f=fab.getBoundingClientRect(),c=card.getBoundingClientRect();
    const abs=x=>({top:x.top+scrollY,bottom:x.bottom+scrollY,left:x.left,right:x.right});
    const fa=abs(f);
    // Every visible form control, measured in page coordinates.
    const covered=[...document.querySelectorAll('input,select,button,label')].filter(e=>e.offsetParent).map(e=>({e,b:abs(e.getBoundingClientRect())}))
      .filter(({b})=>b.left<fa.right&&b.right>fa.left&&b.top<fa.bottom&&b.bottom>fa.top).map(({e})=>e.tagName+'#'+(e.id||e.className));
    return {position:getComputedStyle(fab).position,below:fa.top>=abs(c).bottom-1,inside:f.left>=0&&f.right<=innerWidth,covered,overflow:document.documentElement.scrollWidth>innerWidth+2};
   });
   if(width<=600){assert.equal(r.position,'static',label+': in page flow');assert(r.below,label+': below the card');}
   else assert.equal(r.position,'fixed',label+': still a floating button');
   if(r.position==='static')assert.deepEqual(r.covered,[],label+': covers no form control');
   assert(r.inside,label+': inside the viewport');assert.equal(r.overflow,false,label+': no horizontal scroll');assert.deepEqual(errors,[]);
   if(process.env.DSH_LOGO_SCREENSHOTS)await page.screenshot({path:path.join(process.env.DSH_LOGO_SCREENSHOTS,'login-manual-'+label+'.png'),fullPage:true});
   await page.close();
  }
 }finally{await browser.close();}
 console.log(JSON.stringify({passed:true,checks:['floating on desktop and tablet','in page flow below the card on phones','covers no form control on phones','no overflow or page errors']}));
}finally{if(gateway&&gateway.exitCode===null&&gateway.signalCode===null){await new Promise(r=>{gateway.once('exit',r);gateway.kill();});}fs.rmSync(root,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
