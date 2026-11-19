(()=>{'use strict';
if(document.getElementById('dsh-agent-confirm'))return;
const link=document.getElementById('dsh-agent-tasks'),baseLabel=link?link.textContent:'';let token=null,busy=false,shownId=null,card=null,timer=null,failures=0;
const api=async(path,options={})=>{options.credentials='same-origin';options.cache='no-store';options.headers={...(options.headers||{}),'X-DSH-Agent-CSRF':token};if(options.body)options.headers['Content-Type']='application/json';
 const r=await fetch(path,options);let v=null;try{v=await r.json();}catch{}if(!r.ok)throw Object.assign(Error((v&&v.error)||'Request failed'),{status:r.status});return v;};
const el=(tag,css,text)=>{const e=document.createElement(tag);if(css)e.style.cssText=css;if(text!==undefined)e.textContent=text;return e;};
function remove(){if(card){card.remove();card=null;shownId=null;}}
function badge(n){if(link)link.textContent=n?baseLabel+' · '+n+' waiting':baseLabel;}
function render(p,count){
 if(card&&shownId===p.id)return;remove();shownId=p.id;
 card=el('section','position:fixed;left:16px;bottom:16px;z-index:2147483646;width:min(460px,calc(100vw - 32px));max-height:calc(100vh - 32px);overflow:auto;box-sizing:border-box;padding:16px;border:1px solid #eab308;border-radius:12px;background:#172033;color:#f8fafc;font:14px/1.5 system-ui;box-shadow:0 8px 30px #0008');
 card.id='dsh-agent-confirm';card.setAttribute('role','alertdialog');card.setAttribute('aria-label','Confirm agent task');
 card.appendChild(el('strong','display:block;margin-bottom:6px','An agent asks to run a task'+(count>1?' ('+count+' waiting)':'')));
 card.appendChild(el('div','color:#cbd5e1','Runtime: '+p.runtime+' · Project: '+p.project+' · '+(p.writes?'MAY EDIT FILES':'read-only')));
 const prompt=el('pre','white-space:pre-wrap;word-break:break-word;background:#071522;color:#e7f2ff;padding:10px;border-radius:8px;max-height:220px;overflow:auto;margin:10px 0',p.prompt);card.appendChild(prompt);
 card.appendChild(el('div','color:#94a3b8;font-size:12px','Prompt fingerprint '+p.promptSha256.slice(0,12)+' · you are confirming exactly the text above.'));
 const status=el('div','margin-top:6px;color:#fde68a;min-height:1.4em');status.setAttribute('role','status');
 const row=el('div','display:flex;gap:8px;margin-top:10px;flex-wrap:wrap');
 const mk=(label,bg,fn)=>{const b=el('button','padding:9px 14px;border:0;border-radius:8px;font:600 14px system-ui;cursor:pointer;color:#0b1220;background:'+bg,label);b.type='button';b.onclick=async()=>{if(busy)return;busy=true;row.querySelectorAll('button').forEach(x=>x.disabled=true);
  try{await fn();status.textContent=label==='Confirm and run'?'Confirmed. The task is starting.':'Denied.';setTimeout(()=>{remove();poll();},1200);}catch(e){status.textContent=e.message==='PROPOSAL_EXPIRED'?'This request expired. Ask the agent again.':'Could not complete: '+e.message;row.querySelectorAll('button').forEach(x=>x.disabled=false);}finally{busy=false;}};return b;};
 row.appendChild(mk('Confirm and run','#86efac',()=>api('/api/agent-tasks/'+p.id+'/confirm',{method:'POST',body:JSON.stringify({promptSha256:p.promptSha256})})));
 row.appendChild(mk('Deny','#fca5a5',()=>api('/api/agent-tasks/'+p.id+'/deny',{method:'POST'})));
 card.appendChild(row);card.appendChild(status);document.body.appendChild(card);
}
async function poll(){clearTimeout(timer);
 try{if(!token){token=(await (await fetch('/api/agent-tasks/csrf',{credentials:'same-origin',cache:'no-store'})).json()).token;}
  if(!document.hidden&&!busy){const v=await api('/api/agent-tasks/proposed');const list=(v.proposals||[]).filter(p=>p.state==='proposed'&&typeof p.prompt==='string'&&/^[a-f0-9]{64}$/.test(p.promptSha256||''));
   badge(list.length);if(!list.length)remove();else if(v.signing===false){remove();badge(list.length);}else render(list[0],list.length);}
  failures=0;}catch(e){failures++;if(e.status===401||e.status===403)token=null;}
 timer=setTimeout(poll,failures>3?60000:8000);}
document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll();});window.addEventListener('dsh-session-restored',poll);poll();})();
