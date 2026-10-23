'use strict';
const crypto = require('node:crypto');
const privateLocalPort = port => !Number.isInteger(port) || port < 1024 || port > 65535 || [3080,3081,4000,4001,7681,8888].includes(port);
const isSharedPolicy = value => ['signed-in-users','selected-users','local-users','ldap-users','selected-local-users'].includes(value);
function appVisitorAllowed(item, user, account) {
  if(user===item?.owner)return true;
  if(item?.visitorPolicy==='signed-in-users')return true;
  if(item?.visitorPolicy==='local-users')return !!account && account.disabled!==true && account.authProvider!=='ldap';
  if(item?.visitorPolicy==='ldap-users')return !!account && account.disabled!==true && account.authProvider==='ldap';
  if(item?.visitorPolicy==='selected-local-users')return !!account && account.disabled!==true && account.authProvider!=='ldap' && Array.isArray(item.allowedUsers) && item.allowedUsers.includes(user);
  return item?.visitorPolicy==='selected-users' && Array.isArray(item.allowedUsers) && item.allowedUsers.includes(user);
}
function sharedTarget(item) {
  const mode=item?.sharedEnvironment;
  if(item?.accessMode!=='authenticated'||!isSharedPolicy(item.visitorPolicy)||!['off','on'].includes(mode))throw Error('Unavailable shared application');
  if(['selected-users','selected-local-users'].includes(item.visitorPolicy)&&(!Array.isArray(item.allowedUsers)||!item.allowedUsers.length||item.allowedUsers.length>128||item.allowedUsers.some(u=>typeof u!=='string'||!/^[a-z0-9_.-]{1,64}$/.test(u))||new Set(item.allowedUsers).size!==item.allowedUsers.length))throw Error('Invalid selected application users');
  const ports=Object.keys(item.ports||{}),targets=Object.keys(item.targets||{});
  if(item.targets?.[mode]?.type==='external'&&!ports.length)return {type:'external',mode};
  if(ports.length===1&&ports[0]===mode&&!targets.length&&!privateLocalPort(item.ports[mode]))return {type:'port',mode,port:item.ports[mode]};
  throw Error('Shared local applications require one non-management port in one environment');
}
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// Presentation and return routing only. Password verification and session creation
// remain in the normal issuer. No caller-supplied URL or identity is trusted.
class AppSignIn {
  constructor({domain, issuer, mappings, now = Date.now, limit = 1024, allowedName = () => true, testIssuer = false, ldapEnabled = false}) {
    if (!/^(?:[a-z0-9-]+\.)+[a-z]{2,}$/.test(domain)) throw Error('Invalid app domain');
    if (new URL(issuer).origin !== issuer || !issuer.startsWith('https://')) throw Error('Invalid issuer');
    Object.assign(this, {domain, issuer, mappings, now, limit, allowedName, testIssuer, ldapEnabled});
    this.pending = new Map();
  }
  mapping(name, internet) {
    if (!/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(name || '') || !this.allowedName(name)) throw Error('Unknown application');
    const all = this.mappings(), item = Object.hasOwn(all, name) ? all[name] : null;
    const shared=isSharedPolicy(item?.visitorPolicy);
    if(shared){
      sharedTarget(item);
      internet=item.sharedEnvironment;
    } else if (internet === undefined && item) internet = item.targets?.off || item.ports?.off ? 'off' : 'on';
    if (!item || item.enabled === false || !/^[a-z0-9_.-]{1,64}$/.test(item.owner || '') || !['off','on'].includes(internet) || (!item.targets?.[internet] && !item.ports?.[internet]) || item.accessMode === 'public') throw Error('Unavailable gated application');
    return {name, owner:item.owner, internet, visitorPolicy:shared?item.visitorPolicy:'owner-only', allowedUsers:shared&&['selected-users','selected-local-users'].includes(item.visitorPolicy)?[...item.allowedUsers]:[], sessionInternet:shared?'off':internet, destination:`https://${name}.${this.domain}/`, stamp:crypto.createHash('sha256').update(JSON.stringify(item)).digest('hex')};
  }
  begin(name, res, error = '', internet, authProvider = this.ldapEnabled ? 'ldap' : 'local') {
    const app = this.mapping(name, internet);
    // Chromium applies form-action to the post-login redirect as well as POST.
    // Permit only this validated application's origin, never an arbitrary URL.
    res.setHeader('Content-Security-Policy', `default-src 'none'; style-src 'unsafe-inline'; form-action 'self' ${new URL(app.destination).origin}; base-uri 'none'; frame-ancestors 'none'`);
    for (const [key, value] of this.pending) if (value.expires <= this.now()) this.pending.delete(key);
    if (this.pending.size >= this.limit) throw Error('Sign-in capacity unavailable');
    const token = crypto.randomBytes(32).toString('hex'), browser = crypto.randomBytes(32).toString('hex');
    this.pending.set(token, {...app, browser:crypto.createHash('sha256').update(browser).digest('hex'), expires:this.now()+300000});
    res.setHeader('Set-Cookie', `__Host-dsh_app_login=${browser}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=300`);
    const accessText=this.testIssuer?'Isolated Test issuer. Use the synthetic review account, not your normal DSH credentials.':['selected-users','selected-local-users'].includes(app.visitorPolicy)?'Only the owner and selected enabled accounts can open this application.':app.visitorPolicy==='local-users'?'Use an enabled local DSH account.':app.visitorPolicy==='ldap-users'?'Use an enabled AD / LDAP account.':app.visitorPolicy==='signed-in-users'?'Use any enabled DSH account. The destination application keeps its own permissions.':'This private application is restricted to its authorized owner.';
    return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Sign in to ${escape(name)}</title><style>body{font:18px/1.5 system-ui;max-width:420px;margin:10vh auto;padding:24px}label,input,select,button{display:block;box-sizing:border-box;width:100%;margin:12px 0}input,select,button{padding:12px}p[role=alert]{color:#b91c1c}</style></head><body><h1>Sign in to ${escape(name)}</h1><p>${escape(accessText)}</p>${error?`<p role="alert">${escape(error)}</p>`:''}<p>Application target environment: ${app.internet==='on'?'Internet':'No Internet'}. Signing in does not grant workspace or network access.</p><form method="post" action="/login"><input type="hidden" name="app_login" value="${token}">${this.ldapEnabled?`<label>Sign in using<select name="auth_provider"><option value="ldap" ${authProvider==='ldap'?'selected':''}>AD / LDAP</option><option value="local" ${authProvider==='local'?'selected':''}>Local DSH account</option></select></label>`:''}<label>Username<input name="username" autocomplete="username" required maxlength="64"></label><label>Password<input type="password" name="password" autocomplete="current-password" required maxlength="1024"></label><button>Sign in and open application</button></form><p>The application may require its own sign-in after this access check.</p></body></html>`;
  }
  consume(req, params, canonicalize = value => value.trim().toLowerCase()) {
    const tokens = params.getAll('app_login');
    if (tokens.length !== 1) throw Error('Invalid application sign-in');
    const token = tokens[0], saved = this.pending.get(token);
    // One use even on failed credentials, missing cookies or cross-origin attempts.
    this.pending.delete(token);
    if (!saved || saved.expires <= this.now()) throw Error('Sign-in expired');
    if (req.headers.origin !== this.issuer || req.headers.host !== new URL(this.issuer).host) throw Error('Same-origin sign-in required');
    const cookies = String(req.headers.cookie || '').split(';').map(x=>x.trim()).filter(x=>x.startsWith('__Host-dsh_app_login='));
    if (cookies.length !== 1 || !/^[a-f0-9]{64}$/.test(cookies[0].split('=')[1])) throw Error('Sign-in browser mismatch');
    const digest = crypto.createHash('sha256').update(cookies[0].split('=')[1]).digest('hex');
    if (!crypto.timingSafeEqual(Buffer.from(digest,'hex'),Buffer.from(saved.browser,'hex'))) throw Error('Sign-in browser mismatch');
    const current = this.mapping(saved.name, saved.internet);
    if (current.stamp !== saved.stamp) throw Error('Application configuration changed');
    if (params.getAll('username').length !== 1 || params.getAll('password').length !== 1 || params.get('username').length > 320) throw Error('Account cannot access this application');
    // The issuer supplies its configured AD normalizer. Canonicalization is not
    // authentication; the normal directory bind still runs before session creation.
    const username = canonicalize(params.get('username'));
    if (!/^[a-z0-9_.-]{1,64}$/.test(username) || (['owner-only','signed-in-users','selected-users'].includes(current.visitorPolicy)&&!appVisitorAllowed(current,username))) throw Error('Account cannot access this application');
    return current;
  }
  assertCurrent(saved) {
    const current = this.mapping(saved.name, saved.internet);
    if (current.stamp !== saved.stamp || current.owner !== saved.owner) throw Error('Application configuration changed');
    return current;
  }
}
module.exports = {AppSignIn,sharedTarget,privateLocalPort,isSharedPolicy,appVisitorAllowed};
