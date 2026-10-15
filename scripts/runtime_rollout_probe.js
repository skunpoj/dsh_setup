// Run inside the gateway. Temporary credentials stay on its private auth PVC;
// stdout contains only test results. Never read or print other users' passwords.
const fs = require('fs');
const http = require('http');
const crypto = require('crypto');
const root = '/auth';
const privateFile = `${root}/.runtime-rollout-probe.json`;
const storeFile = process.env.DSH_USER_STORE_PATH;
function read(file) { return JSON.parse(fs.readFileSync(file, 'utf8')); }
function write(file, value) {
  const temporary = `${file}.probe-${process.pid}`;
  fs.writeFileSync(temporary, JSON.stringify(value, null, 2), { mode: 0o600 });
  fs.renameSync(temporary, file);
}
function request(method, url, body = '', cookie = '', contentType = 'application/x-www-form-urlencoded') {
  return new Promise((resolve, reject) => {
    const req = http.request({ host:'127.0.0.1',port:3080,path:url,method,
      headers:{host:'dsh.aiportal.bot.or.th',cookie,'content-type':contentType,
               'content-length':Buffer.byteLength(body)} },res=>{
      let text='';res.on('data',chunk=>text+=chunk);res.on('end',()=>resolve({status:res.statusCode,text,cookies:res.headers['set-cookie']||[]}));
    });req.setTimeout(10000,()=>req.destroy(new Error('probe timeout')));req.on('error',reject);req.end(body);
  });
}
(async()=>{
  const operation=process.argv[2]||'verify';
  if(operation==='prepare') {
    if(fs.existsSync(privateFile)) throw new Error('Probe already provisioned; reuse or clean it up');
    const users=read(storeFile);const user=`rtcheck_${Date.now().toString(36)}`;
    if(Object.hasOwn(users,user))throw new Error('Probe identity collision');
    const password=crypto.randomBytes(32).toString('hex');
    fs.writeFileSync(privateFile,JSON.stringify({user,password}),{mode:0o600,flag:'wx'});
    users[user]=password;write(storeFile,users);console.log(JSON.stringify({temporaryProbeProvisioned:true}));return;
  }
  const identity=read(privateFile);
  if(operation==='hold') {
    identity.heldSessions=[];
    for(const environment of ['off','on']) {
      const login=await request('POST','/login',new URLSearchParams({username:identity.user,password:identity.password,internet:environment}).toString());
      if(login.status!==302)throw new Error('Could not establish held session');
      identity.heldSessions.push({environment,cookie:login.cookies.map(item=>item.split(';')[0]).join('; ')});
    }
    write(privateFile,identity);console.log(JSON.stringify({heldSessionsCreated:2}));return;
  }
  if(operation==='resume') {
    const results=[];
    for(const session of identity.heldSessions||[]) {
      const response=await request('GET','/','',session.cookie);
      results.push({environment:session.environment,status:response.status,authenticatedUI:response.text.includes('dsh-enterprise-logout')});
    }
    console.log(JSON.stringify({time:new Date().toISOString(),heldSessionResults:results}));
    if(results.length!==2||results.some(item=>item.status!==200||!item.authenticatedUI))process.exitCode=1;
    return;
  }
  if(operation==='cleanup') {
    for(const session of identity.heldSessions||[])await request('GET','/logout','',session.cookie);
    const users=read(storeFile);if(users[identity.user]!==identity.password)throw new Error('Probe changed; do not remove another credential');
    delete users[identity.user];const expected=JSON.stringify(Object.entries(users).sort());write(storeFile,users);
    const otherAccountsUnchanged=JSON.stringify(Object.entries(read(storeFile)).sort())===expected;
    const settingsFile=process.env.DSH_USER_SETTINGS_PATH;
    if(fs.existsSync(settingsFile)){const settings=read(settingsFile);delete settings[identity.user];write(settingsFile,settings);}
    fs.unlinkSync(privateFile);console.log(JSON.stringify({temporaryProbeRemoved:true,otherAccountsUnchanged}));
    if(!otherAccountsUnchanged)process.exitCode=1;return;
  }
  const results=[];
  for(const environment of ['off','on']) {
    const login=await request('POST','/login',new URLSearchParams({username:identity.user,password:identity.password,internet:environment}).toString());
    const cookie=login.cookies.map(item=>item.split(';')[0]).join('; ');
    const session=await request('GET','/api/auth/session','',cookie);
    const ui=await request('GET','/','',cookie);
    const terminal=await request('GET','/proxy/7681/','',cookie);
    const historyResponse=await request('POST','/api/session/list',JSON.stringify({type:'client-request',rpcId:'rollout-history-probe',method:'session/list',payload:{args:{_request:{}}}}),cookie,'application/json');
    let history;try{history=JSON.parse(historyResponse.text);}catch{}
    const logout=await request('GET','/logout','',cookie);
    const afterLogout=await request('GET','/api/auth/session','',cookie);
    let info;try{info=JSON.parse(session.text);}catch{}
    results.push({environment,loginStatus:login.status,sessionEnvironment:info?.environment,
       uiStatus:ui.status,uiIsHTML:/<!doctype html|<html/i.test(ui.text),logoutButton:ui.text.includes('dsh-enterprise-logout'),
       secureCookie:login.cookies.some(item=>/; Secure(?:;|$)/i.test(item)),
       historyListed:history?.result?.ok===true,historyCount:history?.result?.value?.items?.length,
       terminalPage:terminal.status===200&&/ttyd|terminal/i.test(terminal.text)&&!terminal.text.includes('id="pane-login"'),
       logoutStatus:logout.status,logoutInvalidatesSession:afterLogout.text.includes('id="pane-login"')});
  }
  console.log(JSON.stringify({time:new Date().toISOString(),results}));
  if(results.some(item=>item.loginStatus!==302||item.uiStatus!==200||!item.uiIsHTML||!item.logoutButton||!item.logoutInvalidatesSession||!item.historyListed||!item.secureCookie||!item.terminalPage))process.exitCode=1;
})().catch(error=>{console.error(error.message);process.exitCode=1});
