const http = require('http');
const url = require('url');
const fs = require('fs');
const crypto = require('crypto');

const PROXY_PORT = Number(process.env.PORT || 3080);
// Kubernetes may inject DSH_PORT=tcp://<service-ip>:3080 for the Service named
// "dsh". Accept only an explicitly numeric port and otherwise use the internal
// DSH web port, avoiding an invalid 127.0.0.1:NaN proxy target.
const requestedDshPort = process.env.DSH_TARGET_PORT || process.env.DSH_PORT || '';
const DSH_TARGET_PORT = /^\d+$/.test(requestedDshPort) ? Number(requestedDshPort) : 3081;
const DSH_TARGET_HOST = process.env.DSH_HOST || '127.0.0.1';
const USER_ROOT = process.env.WORKSPACE_ROOT || '/workspace/users';
const USER_STORE_PATH = process.env.DSH_USER_STORE_PATH || `${USER_ROOT}/.user_auth.json`;
const USER_SETTINGS_PATH = process.env.DSH_USER_SETTINGS_PATH || `${USER_ROOT}/.user_settings.json`;
const COOKIE_NAME = process.env.DSH_COOKIE_NAME || 'dsh_auth';
const COOKIE_TRANSPORT = process.env.DSH_COOKIE_SECURE === 'false' ? '' : '; Secure';
const ADMIN_USERS = new Set((process.env.DSH_ADMIN_USERS || 'admin').split(',').map(x => x.trim()).filter(Boolean));
const ADMIN_SUMMARY_FILE = process.env.DSH_ADMIN_SUMMARY_FILE || '/admin-status/summary.json';
const AUDIT_DIR = process.env.DSH_AUDIT_DIR || `${USER_ROOT}/audit`;
let auditFailures = 0;
function auditEvent(event, actor, mode) {
  try {
    fs.mkdirSync(AUDIT_DIR, { recursive: true, mode: 0o700 });
    const file = `${AUDIT_DIR}/events.jsonl`;
    if (fs.existsSync(file) && fs.statSync(file).size >= 5 * 1024 * 1024) {
      // Preserve old records; stop rather than silently delete an audit archive.
      if (fs.existsSync(`${AUDIT_DIR}/events.5.jsonl`)) throw new Error('Audit retention capacity reached');
      for (let i = 4; i >= 1; i--) if (fs.existsSync(`${AUDIT_DIR}/events.${i}.jsonl`)) fs.renameSync(`${AUDIT_DIR}/events.${i}.jsonl`, `${AUDIT_DIR}/events.${i+1}.jsonl`);
      fs.renameSync(file, `${AUDIT_DIR}/events.1.jsonl`);
    }
    const user = typeof actor === 'string' && /^[a-zA-Z0-9_.-]{1,30}$/.test(actor) ? actor : 'unidentified';
    fs.appendFileSync(file, JSON.stringify({ time: new Date().toISOString(), event, user,
      environment: normalizeInternetMode(mode) === 'on' ? 'internet' : 'secure' }) + '\n', { mode: 0o600 });
    return true;
  } catch { auditFailures++; console.error('[AUDIT] Could not persist security event'); return false; }
}
function recentAudit() {
  try { return fs.readFileSync(`${AUDIT_DIR}/events.jsonl`, 'utf8').trim().split('\n').filter(Boolean).slice(-100).map(line => {
    const r = JSON.parse(line);return {time:r.time,event:r.event,user:r.user,environment:r.environment};
  }); } catch { return []; }
}

function adminSummary() {
  let saved = {};
  try { saved = JSON.parse(fs.readFileSync(ADMIN_SUMMARY_FILE, 'utf8')); } catch {}
  const sessions = { secure: 0, internet: 0 };
  for (const s of SESSIONS.values()) sessions[normalizeInternetMode(s.internet) === 'on' ? 'internet' : 'secure']++;
  // Explicit projection prevents accidental publication of credentials or raw
  // Kubernetes configuration from an operator-supplied snapshot.
  return { generatedAt: new Date().toISOString(), registeredAccounts: Object.keys(loadUsers()).length,
    activeBrowserSessions: sessions, privateUserRouting: Boolean(USER_TARGETS), registrationEnabled: ALLOW_REGISTRATION,
    audit: { failuresSinceStart: auditFailures, recentEvents: recentAudit().length },
    snapshot: { observedAt: typeof saved.observedAt === 'string' ? saved.observedAt : null,
      environments: Array.isArray(saved.environments) ? saved.environments.map(e => ({ name: String(e.name || ''),
        ready: e.ready === true, storage: String(e.storage || ''), network: String(e.network || '') })) : [],
      model: saved.model ? { backendContext: Number(saved.model.backendContext) || null,
        userContext: Number(saved.model.userContext) || null, concurrencyCeiling: Number(saved.model.concurrencyCeiling) || null } : null,
      performance: Array.isArray(saved.performance) ? saved.performance.map(String) : [],
      gaps: Array.isArray(saved.gaps) ? saved.gaps.map(String) : [] } };
}

function renderAdminDashboard() {
  return `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DSH Admin overview</title>
<style>body{font:16px/1.6 system-ui;background:#f1f5f9;color:#172033;margin:0}main{max-width:1100px;margin:auto;padding:32px}a{color:#075985}header{display:flex;gap:24px;align-items:center;flex-wrap:wrap}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}section{background:white;border:1px solid #cbd5e1;border-radius:12px;padding:20px;margin:18px 0}h1,h2{line-height:1.2}strong{font-size:24px}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:10px;border-bottom:1px solid #e2e8f0}.muted{color:#475569}.notice{border-left:5px solid #d97706}button{padding:8px 16px;cursor:pointer}</style>
<main><header><h1>DSH Admin overview</h1><a href="/">Back to DSH</a><a href="/logout">Logout</a><button id="refresh">Refresh</button></header><p id="error" role="alert"></p><p id="time" class="muted"></p>
<div class="cards"><section>Registered accounts<br><strong id="accounts">—</strong></section><section>Active browser sessions<br><strong id="sessions">—</strong><div id="sessionDetail"></div></section><section>User routing<br><strong id="routing">—</strong></section></div>
<section class="notice"><h2>Evidence freshness</h2><p id="freshness"></p><p>Account/session counts and routing are current gateway values. Environment health, storage, limits and performance below are an operator-recorded snapshot, not live monitoring. Browser logins are not unique users or model requests.</p></section>
<section><h2>Execution environments</h2><div style="overflow:auto"><table><thead><tr><th>Environment</th><th>Recorded readiness</th><th>Storage</th><th>Recorded network behavior</th></tr></thead><tbody id="environments"></tbody></table></div></section>
<section><h2>Model limits</h2><p id="model"></p><p class="muted">A concurrency ceiling does not guarantee that many maximum-length requests fit.</p></section><section><h2>Recorded performance</h2><ul id="performance"></ul></section><section><h2>Central access audit</h2><p id="audit"></p><a href="/api/admin/audit">Read recent access events</a></section><section class="notice"><h2>Remaining controls</h2><ul id="gaps"></ul></section><p class="muted">Read-only overview. No passwords, cookies, conversation contents or source records are displayed.</p></main>
<script>
const put=(id,value)=>document.getElementById(id).textContent=value;
function list(id,values){const root=document.getElementById(id);root.replaceChildren();for(const value of values){const li=document.createElement('li');li.textContent=value;root.append(li);}}
async function refresh(){try{const r=await fetch('/api/admin/summary',{cache:'no-store',credentials:'same-origin'});if(!r.ok)throw Error('Admin access unavailable ('+r.status+').');const d=await r.json();put('error','');put('time','Gateway read at '+d.generatedAt);put('accounts',d.registeredAccounts);put('sessions',d.activeBrowserSessions.secure+d.activeBrowserSessions.internet);put('sessionDetail','No Internet: '+d.activeBrowserSessions.secure+' · Internet: '+d.activeBrowserSessions.internet);put('routing',d.privateUserRouting?'Per user':'Shared pools');put('freshness',d.snapshot.observedAt?'Snapshot observed at '+d.snapshot.observedAt+'. Refresh does not rerun infrastructure tests.':'No snapshot available. Infrastructure status is unknown.');const root=document.getElementById('environments');root.replaceChildren();for(const e of d.snapshot.environments){const tr=document.createElement('tr');for(const text of [e.name,e.ready?'Ready at observation':'Not verified ready',e.storage,e.network]){const td=document.createElement('td');td.textContent=text;tr.append(td);}root.append(tr);}const m=d.snapshot.model;put('model',m?'Backend context: '+m.backendContext+' tokens · DSH/LiteLLM budget: '+m.userContext+' tokens · Running-request ceiling: '+m.concurrencyCeiling:'No recorded limits.');list('performance',d.snapshot.performance);list('gaps',d.snapshot.gaps);}catch(e){put('error',e.message);}}
document.getElementById('refresh').addEventListener('click',refresh);refresh().then(async()=>{try{const r=await fetch('/api/admin/summary',{cache:'no-store'});const d=await r.json();put('audit','Recent recorded events: '+d.audit.recentEvents+' · Write failures since gateway start: '+d.audit.failuresSinceStart);}catch{put('audit','Audit status unavailable.');}});
</script></html>`;
}

// A gateway can route an authenticated session to a dedicated execution pool.
// When these variables are absent the proxy keeps its original single-pod behaviour.
const ENVIRONMENT_TARGETS = {
  off: {
    name: 'secure',
    host: process.env.DSH_OFFLINE_HOST || DSH_TARGET_HOST,
    port: Number(process.env.DSH_OFFLINE_PORT || DSH_TARGET_PORT),
    tokenFile: process.env.DSH_OFFLINE_TOKEN_FILE || '/tmp/dsh_token.txt',
  },
  on: {
    name: 'internet',
    host: process.env.DSH_ONLINE_HOST || DSH_TARGET_HOST,
    port: Number(process.env.DSH_ONLINE_PORT || DSH_TARGET_PORT),
    tokenFile: process.env.DSH_ONLINE_TOKEN_FILE || '/tmp/dsh_token.txt',
  },
};

// Provisioned by an operator. No request header, URL, or form can choose a host.
// Enabling isolation makes missing identities fail closed rather than share a pool.
const USER_TARGETS = process.env.DSH_USER_TARGETS_FILE
  ? JSON.parse(fs.readFileSync(process.env.DSH_USER_TARGETS_FILE, 'utf8')) : null;
// Pilot accounts are provisioned by an administrator. Isolated routing always
// disables registration, including when a legacy opt-in variable is present.
const ALLOW_REGISTRATION = !USER_TARGETS && process.env.DSH_ALLOW_REGISTRATION === 'true';
if (USER_TARGETS) {
  for (const [user, targets] of Object.entries(USER_TARGETS)) {
    if (!/^[a-z0-9_\-.]{3,30}$/.test(user)) throw new Error('Invalid provisioned identity');
    for (const target of Object.values(targets)) {
      if (!target || !/^[a-zA-Z0-9.-]+$/.test(target.host) ||
          !Number.isInteger(target.port) || target.port < 1024 || target.port > 65535 ||
          typeof target.tokenFile !== 'string' || !target.tokenFile.startsWith('/runtime-tokens/')) {
        throw new Error('Invalid provisioned runtime target');
      }
    }
  }
}
function getEnvironmentTarget(mode, user) {
  if (USER_TARGETS) {
    const environment = normalizeInternetMode(mode) === 'on' ? 'internet' : 'secure';
    const targets = Object.prototype.hasOwnProperty.call(USER_TARGETS, user) ? USER_TARGETS[user] : null;
    const target = targets && targets[environment];
    return target ? { ...target, name: environment } : null;
  }
  return ENVIRONMENT_TARGETS[normalizeInternetMode(mode)];
}

// The session cookie is shared with the app subdomains (dsh-<port>.<parent>) through its Domain
// attribute. The domain comes from configuration, never from the request's Host header, and
// defaults to the parent of DSH_TRUSTED_HOST (dsh.example.com -> .example.com); a host with
// fewer than three labels gets a host-only cookie.
function getCookieDomain() {
  if (process.env.DSH_COOKIE_DOMAIN) {
    const d = process.env.DSH_COOKIE_DOMAIN;
    return d.startsWith('.') ? `; Domain=${d}` : `; Domain=.${d}`;
  }
  const trusted = (process.env.DSH_TRUSTED_HOST || '').split(':')[0].toLowerCase();
  if (!trusted || /^(\d{1,3}\.){3}\d{1,3}$/.test(trusted)) return '';
  const parts = trusted.split('.');
  if (parts.length >= 3) {
    return '; Domain=.' + parts.slice(1).join('.');
  }
  return '';
}

// Proxy session cookies (this tenant's, the legacy dsh_auth name, and DSH's dsh-auth-*) are
// removed before a request reaches a user app, so an app cannot read and replay them.
function stripAuthCookies(cookieHeader) {
  if (!cookieHeader) return '';
  return cookieHeader.split(';').map(c => c.trim()).filter(c => c &&
    !c.startsWith(`${COOKIE_NAME}=`) && !c.startsWith('dsh_auth=') && !c.startsWith('dsh-auth-')).join('; ');
}

// In-memory sessions
const SESSIONS = new Map();
const cachedDshAuthCookies = new Map();

// --- DYNAMIC APP GATEWAY HELPERS (OPTION 1 & OPTION 2) ---
function resolvePortAlias(alias) {
  if (!alias) return null;
  const key = alias.toLowerCase();
  try {
    const portsPath = '/workspace/.ports.json';
    if (fs.existsSync(portsPath)) {
      const mapping = JSON.parse(fs.readFileSync(portsPath, 'utf8'));
      if (mapping && mapping[key]) {
        return parseInt(mapping[key], 10);
      }
    }
  } catch (e) {
    console.error('[AUTH-PROXY] Error reading .ports.json:', e.message);
  }
  const defaults = {
    'terminal': 7681,
    'ttyd': 7681,
    'streamlit': 8501,
    'dashboard': 8501,
    'api': 8000,
    'fastapi': 8000,
    'web': 3000
  };
  return defaults[key] || null;
}

function parseAppTarget(inHost, reqUrl) {
  const parsed = url.parse(reqUrl, true);
  let port = null;
  let targetPath = reqUrl;

  // 1. Subdomain Check: e.g. dsh-8000.example.com, dsh2-8501, dsh-user2-8000...
  // dsh-user<N> is tried before dsh<N> so dsh-user2-8000 resolves to port 8000, not alias "user2-8000".
  const subMatch = inHost.match(/^(?:dsh-user[0-9]*|dsh[0-9]*)-([a-zA-Z0-9_-]+)\./i);
  if (subMatch) {
    const raw = subMatch[1];
    if (/^\d+$/.test(raw)) {
      port = parseInt(raw, 10);
    } else {
      port = resolvePortAlias(raw);
    }
    targetPath = reqUrl; // Root path preserved for SPA / assets
  }

  // 2. Path Check: e.g. /proxy/8000/ or /proxy/myapp/api
  if (!port) {
    const pathMatch = parsed.pathname.match(/^\/proxy\/([a-zA-Z0-9_-]+)(\/.*)?$/);
    if (pathMatch) {
      const raw = pathMatch[1];
      if (/^\d+$/.test(raw)) {
        port = parseInt(raw, 10);
      } else {
        port = resolvePortAlias(raw);
      }
      targetPath = (pathMatch[2] || '/') + (parsed.search || '');
    }
  }

  // Only user app ports are forwarded; the gateway and DSH ports are never app targets.
  if (!Number.isInteger(port) || port < 1 || port > 65535 || port === PROXY_PORT || port === DSH_TARGET_PORT) {
    port = null;
  }
  return { port, targetPath };
}

function forwardToLocalApp(targetPort, targetPath, req, res, targetHost = '127.0.0.1') {
  const proxyHeaders = { ...req.headers };
  proxyHeaders['host'] = `127.0.0.1:${targetPort}`;
  proxyHeaders['x-forwarded-host'] = req.headers.host;
  const appCookies = stripAuthCookies(req.headers.cookie);
  if (appCookies) {
    proxyHeaders['cookie'] = appCookies;
  } else {
    delete proxyHeaders['cookie'];
  }
  proxyHeaders['x-forwarded-proto'] = req.headers['x-forwarded-proto'] || 'https';

  const proxyReq = http.request({
    host: targetHost,
    port: targetPort,
    path: targetPath,
    method: req.method,
    headers: proxyHeaders
  }, (proxyRes) => {
    const resHeaders = { ...proxyRes.headers };
    if (resHeaders['content-type'] && resHeaders['content-type'].includes('text/html')) {
      resHeaders['cache-control'] = 'no-cache, no-store, must-revalidate';
      resHeaders['pragma'] = 'no-cache';
      resHeaders['expires'] = '0';
    }
    res.writeHead(proxyRes.statusCode, resHeaders);
    proxyRes.pipe(res);
  });

  proxyReq.on('error', (err) => {
    console.warn(`[AUTH-PROXY] App forward error on port ${targetPort}:`, err.message);
    res.writeHead(502, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(`<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>DSH App Gateway: Port ${targetPort}</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0B0F19; color: #F8FAFC; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; }
    .card { background: #1E293B; border: 1px solid #334155; border-radius: 12px; padding: 32px; max-width: 540px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); width: 100%; }
    h2 { color: #38BDF8; margin-top: 0; display: flex; align-items: center; gap: 10px; font-size: 20px; }
    code { background: #0F172A; padding: 3px 8px; border-radius: 6px; color: #F43F5E; font-size: 14px; font-family: monospace; }
    p { color: #94A3B8; line-height: 1.6; font-size: 14px; }
    .tip { background: rgba(56, 189, 248, 0.1); border-left: 4px solid #38BDF8; padding: 14px 16px; margin: 20px 0; border-radius: 0 8px 8px 0; font-size: 13px; color: #E2E8F0; }
    .code-block { background: #0F172A; padding: 10px 14px; border-radius: 6px; margin-top: 8px; font-family: monospace; color: #A5F3FC; font-size: 12px; }
  </style>
</head>
<body>
  <div class="card">
    <h2>⚡ DSH Application Gateway</h2>
    <p>Target service on port <code>${targetPort}</code> is currently not listening inside this DSH container.</p>
    <div class="tip">
      <strong>How to start your web application:</strong><br>
      Start your server inside the DSH container terminal or via agent, e.g.:
      <div class="code-block">python -m http.server ${targetPort}</div>
      <div class="code-block">streamlit run app.py --server.port ${targetPort}</div>
      <div class="code-block">uvicorn main:app --host 0.0.0.0 --port ${targetPort}</div>
    </div>
    <p style="font-size: 12px; color: #64748B;">Internal status: ${err.message}</p>
  </div>
</body>
</html>`);
  });

  req.pipe(proxyReq);
}

function bindAuthenticatedProxyIdentity(req, user, internetMode) {
  // Every carrier, including custom applications and raw WebSocket upgrades,
  // receives identity from the authenticated session, never the client.
  req.headers['x-dsh-user'] = user;
  req.headers['x-dsh-internet-access'] = internetMode;
  const raw = [];
  for (let i = 0; i < req.rawHeaders.length; i += 2) {
    const name = req.rawHeaders[i].toLowerCase();
    if (name !== 'x-dsh-user' && name !== 'x-dsh-internet-access') {
      raw.push(req.rawHeaders[i], req.rawHeaders[i + 1]);
    }
  }
  raw.push('X-DSH-User', user, 'X-DSH-Internet-Access', internetMode);
  req.rawHeaders = raw;
}

function forwardWebSocketToLocalApp(targetPort, targetPath, req, socket, head, targetHost = '127.0.0.1') {
  const rawHeaders = req.rawHeaders;
  let upgradeReqText = `${req.method} ${targetPath} HTTP/${req.httpVersion}\r\n`;
  for (let i = 0; i < rawHeaders.length; i += 2) {
    const headerKey = rawHeaders[i];
    let headerVal = rawHeaders[i + 1];
    if (headerKey.toLowerCase() === 'host') {
      headerVal = `127.0.0.1:${targetPort}`;
    }
    if (headerKey.toLowerCase() === 'cookie') {
      headerVal = stripAuthCookies(headerVal);
      if (!headerVal) continue;
    }
    upgradeReqText += `${headerKey}: ${headerVal}\r\n`;
  }
  upgradeReqText += `\r\n`;

  const net = require('net');
  const targetSocket = net.connect(targetPort, targetHost, () => {
    targetSocket.write(upgradeReqText);
    if (head && head.length > 0) {
      targetSocket.write(head);
    }
    socket.pipe(targetSocket);
    targetSocket.pipe(socket);
  });

  targetSocket.on('error', (err) => {
    console.warn(`[AUTH-PROXY] WebSocket forward error on port ${targetPort}:`, err.message);
    socket.destroy();
  });
}

function getOrMintDshCookie(clientHost, target, callback) {
  const cacheKey = `${target.name}|${target.host}|${target.port}|${clientHost}`;
  const token = getDshToken(target.tokenFile);
  if (!token) {
    cachedDshAuthCookies.delete(cacheKey);
    return callback(new Error("No DSH launch token available"));
  }
  const fingerprint = crypto.createHash('sha256').update(token).digest('hex');
  const existing = cachedDshAuthCookies.get(cacheKey);
  if (existing?.fingerprint === fingerprint) return callback(null, existing.cookie);
  cachedDshAuthCookies.delete(cacheKey);
  const authReq = http.request({
    host: target.host,
    port: target.port,
    path: `/?token=${encodeURIComponent(token)}`,
    method: "GET",
    headers: { "host": clientHost }
  }, (authRes) => {
    let mintedCookie = null;
    const setCookies = authRes.headers["set-cookie"];
    if (setCookies) {
      for (const sc of setCookies) {
        if (sc.startsWith("dsh-auth-")) {
          mintedCookie = sc.split(";")[0];
          cachedDshAuthCookies.set(cacheKey, { fingerprint, cookie: mintedCookie });
          console.log(`[AUTH-PROXY] Successfully minted and cached upstream DSH cookie for authority ${clientHost}`);
          break;
        }
      }
    }
    authRes.resume();
    callback(null, mintedCookie);
  });
  authReq.on("error", (err) => {
    callback(err);
  });
  authReq.end();
}

// The admin password comes from environment or existing persistent user store
let adminPass = process.env.DSH_AUTH_PASS;
if (!adminPass && !fs.existsSync(USER_STORE_PATH)) {
  console.error('[AUTH-PROXY] DSH_AUTH_PASS is not set and no user store found; refusing to start.');
  process.exit(1);
}
const DEFAULT_USERS = {
  ...(adminPass ? { 'admin': adminPass } : {})
};

function loadUsers() {
  try {
    if (fs.existsSync(USER_STORE_PATH)) {
      const raw = fs.readFileSync(USER_STORE_PATH, 'utf8');
      const data = JSON.parse(raw);
      return Object.assign({}, DEFAULT_USERS, data);
    }
  } catch (e) {
    console.error('[AUTH-PROXY] Failed to load user store:', e.message);
  }
  return Object.assign({}, DEFAULT_USERS);
}

function saveUsers(users) {
  try {
    fs.mkdirSync(USER_ROOT, { recursive: true });
    fs.writeFileSync(USER_STORE_PATH, JSON.stringify(users, null, 2), 'utf8');
    return true;
  } catch (e) {
    console.error('[AUTH-PROXY] Failed to save user store:', e.message);
    return false;
  }
}

function loadUserSettings() {
  try {
    if (fs.existsSync(USER_SETTINGS_PATH)) {
      const data = JSON.parse(fs.readFileSync(USER_SETTINGS_PATH, 'utf8'));
      if (data && typeof data === 'object' && !Array.isArray(data)) return data;
    }
  } catch (e) {
    console.error('[AUTH-PROXY] Failed to load user settings:', e.message);
  }
  return {};
}

function saveUserSettings(settings) {
  try {
    fs.mkdirSync(USER_ROOT, { recursive: true });
    fs.writeFileSync(USER_SETTINGS_PATH, JSON.stringify(settings, null, 2), { encoding: 'utf8', mode: 0o600 });
    return true;
  } catch (e) {
    console.error('[AUTH-PROXY] Failed to save user settings:', e.message);
    return false;
  }
}

function normalizeInternetMode(value) {
  return value === 'on' ? 'on' : 'off';
}

function setUserInternetMode(username, mode) {
  const settings = loadUserSettings();
  settings[username] = { ...(settings[username] || {}), internet: normalizeInternetMode(mode) };
  return saveUserSettings(settings);
}

function injectLogoutControl(html, isAdmin = false) {
  if (typeof html !== 'string' || html.includes('id="dsh-enterprise-logout"')) return html;
  const control = `<a id="dsh-enterprise-logout" href="/logout" aria-label="ออกจากระบบ (Logout)" title="ออกจากระบบ (Logout)" style="position:fixed;right:18px;top:14px;z-index:2147483647;display:inline-flex;align-items:center;gap:7px;padding:8px 12px;border:1px solid rgba(148,163,184,.42);border-radius:8px;background:rgba(15,23,42,.94);color:#f8fafc;font:600 13px/1.2 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;text-decoration:none;box-shadow:0 4px 14px rgba(0,0,0,.28);backdrop-filter:blur(8px)"><span aria-hidden="true">&#x21AA;</span><span>ออกจากระบบ / Logout</span></a>`;
  const adminLink = isAdmin ? '<a id="dsh-admin-dashboard" href="/admin" style="position:fixed;right:220px;top:14px;z-index:2147483647;background:#0f172a;color:white;padding:8px 12px;border-radius:8px;text-decoration:none;font:600 13px system-ui">Admin overview</a>' : '';
  if (/<\/body>/i.test(html)) return html.replace(/<\/body>/i, `${control}${adminLink}</body>`);
  return html + control + adminLink;
}

// Initialize user store if missing
let USERS = loadUsers();
if (!fs.existsSync(USER_STORE_PATH)) {
  saveUsers(USERS);
}

function getDshToken(tokenFile = '/tmp/dsh_token.txt') {
  try {
    if (fs.existsSync(tokenFile)) {
      return fs.readFileSync(tokenFile, 'utf8').trim();
    }
  } catch (e) {}
  return '';
}

function renderAuthPage({ tab = 'login', errorMsg = '', successMsg = '' } = {}) {
  return `<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Login · DeepSeek Harness (DSH) — Enterprise AI Platform</title>
  <style>
    :root {
      --primary-navy: #0F4C81;
      --primary-deep: #0A2540;
      --primary-gold: #C5A880;
      --bg-dark: #0B0F19;
      --card-bg: #131C2E;
      --border: #202E49;
      --text-main: #E2E8F0;
      --text-muted: #94A3B8;
      --success-bg: rgba(16, 185, 129, 0.15);
      --success-border: rgba(16, 185, 129, 0.35);
      --success-text: #34D399;
      --error-bg: rgba(239, 68, 68, 0.15);
      --error-border: rgba(239, 68, 68, 0.35);
      --error-text: #F87171;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Sarabun', -apple-system, sans-serif; }
    body {
      background-color: var(--bg-dark);
      background-image: radial-gradient(circle at top right, #1a2f4d 0%, transparent 60%), radial-gradient(circle at bottom left, #0d1e38 0%, transparent 60%);
      color: var(--text-main);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }
    .login-card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 16px;
      width: 100%;
      max-width: 460px;
      padding: 36px 32px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255, 255, 255, 0.05);
      position: relative;
      overflow: hidden;
    }
    .login-card::before {
      content: "";
      position: absolute;
      top: 0; left: 0; right: 0;
      height: 4px;
      background: linear-gradient(90deg, var(--primary-gold), #e8d5b5, var(--primary-navy));
    }
    .brand-header {
      text-align: center;
      margin-bottom: 24px;
    }
    .brand-logo {
      width: 52px;
      height: 52px;
      margin: 0 auto 12px;
      background: linear-gradient(135deg, var(--primary-navy), var(--primary-deep));
      border: 1px solid rgba(197, 168, 128, 0.4);
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    }
    .brand-logo svg {
      width: 28px;
      height: 28px;
      fill: var(--primary-gold);
    }
    .org-title {
      font-size: 13px;
      letter-spacing: 1px;
      color: var(--primary-gold);
      font-weight: 600;
      text-transform: uppercase;
    }
    .app-title {
      font-size: 20px;
      font-weight: 700;
      color: #FFF;
      margin: 4px 0 2px;
    }
    .app-subtitle {
      font-size: 12px;
      color: var(--text-muted);
    }

    /* Tabs */
    .auth-tabs {
      display: flex;
      background: rgba(11, 15, 25, 0.7);
      border-radius: 8px;
      padding: 4px;
      margin-bottom: 20px;
      border: 1px solid var(--border);
    }
    .auth-tab {
      flex: 1;
      text-align: center;
      padding: 8px 4px;
      font-size: 13px;
      font-weight: 500;
      color: var(--text-muted);
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.2s;
      text-decoration: none;
    }
    .auth-tab.active {
      background: var(--primary-navy);
      color: #FFF;
      font-weight: 600;
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
    }

    .alert-badge {
      padding: 10px 14px;
      border-radius: 8px;
      font-size: 13px;
      margin-bottom: 18px;
      line-height: 1.4;
    }
    .alert-error {
      background: var(--error-bg);
      border: 1px solid var(--error-border);
      color: var(--error-text);
    }
    .alert-success {
      background: var(--success-bg);
      border: 1px solid var(--success-border);
      color: var(--success-text);
    }

    .form-group {
      margin-bottom: 16px;
    }
    .form-label {
      display: block;
      font-size: 13px;
      font-weight: 500;
      color: var(--text-muted);
      margin-bottom: 6px;
    }
    .form-control {
      width: 100%;
      padding: 11px 14px;
      background: rgba(11, 15, 25, 0.6);
      border: 1px solid var(--border);
      border-radius: 8px;
      color: #FFF;
      font-size: 14px;
      transition: all 0.2s;
    }
    .form-control:focus {
      outline: none;
      border-color: var(--primary-navy);
      box-shadow: 0 0 0 3px rgba(15, 76, 129, 0.25);
      background: rgba(11, 15, 25, 0.9);
    }
    .radio-group {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .radio-option {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 12px;
      background: rgba(11, 15, 25, 0.6);
      border: 1px solid var(--border);
      border-radius: 8px;
      cursor: pointer;
      font-size: 13px;
    }
    .radio-option:has(input:checked) { border-color: var(--primary-navy); background: rgba(15, 76, 129, 0.2); }
    .form-help { margin-top: 6px; color: var(--text-muted); font-size: 11px; line-height: 1.4; }
    .btn-submit {
      width: 100%;
      padding: 12px;
      background: linear-gradient(135deg, var(--primary-navy), #165b99);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 8px;
      color: #FFFFFF;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s;
      box-shadow: 0 4px 12px rgba(15, 76, 129, 0.4);
      margin-top: 6px;
    }
    .btn-submit:hover {
      background: linear-gradient(135deg, #165b99, #1b6cb4);
      transform: translateY(-1px);
    }
    .footer-note {
      text-align: center;
      margin-top: 22px;
      font-size: 11px;
      color: #64748B;
    }
  </style>
  <script>
    function switchTab(name) {
      document.querySelectorAll('.tab-pane').forEach(el => el.style.display = 'none');
      document.querySelectorAll('.auth-tab').forEach(el => el.classList.remove('active'));
      document.getElementById('pane-' + name).style.display = 'block';
      document.getElementById('tab-' + name).classList.add('active');
    }
  </script>
</head>
<body>
  <div class="login-card">
    <div class="brand-header">
      <div class="brand-logo">
        <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>
      </div>
      <div class="org-title">Enterprise AI Platform</div>
      <h1 class="app-title">DeepSeek Harness (DSH)</h1>
      <p class="app-subtitle">Enterprise Agentic Coding & Knowledge Gateway</p>
    </div>

    <div class="auth-tabs">
      <div id="tab-login" class="auth-tab ${tab === 'login' ? 'active' : ''}" onclick="switchTab('login')">เข้าสู่ระบบ</div>
      ${ALLOW_REGISTRATION ? `<div id="tab-register" class="auth-tab ${tab === 'register' ? 'active' : ''}" onclick="switchTab('register')">สร้างบัญชีผู้ใช้ใหม่</div>` : ''}
      <div id="tab-change" class="auth-tab ${tab === 'change' ? 'active' : ''}" onclick="switchTab('change')">เปลี่ยนรหัสผ่าน</div>
    </div>

    ${errorMsg ? `<div class="alert-badge alert-error">⚠️ ${errorMsg}</div>` : ''}
    ${successMsg ? `<div class="alert-badge alert-success">✅ ${successMsg}</div>` : ''}

    <!-- 1. Form: เข้าสู่ระบบ -->
    <div id="pane-login" class="tab-pane" style="display: ${tab === 'login' ? 'block' : 'none'};">
      <form method="POST" action="/login">
        <div class="form-group">
          <label class="form-label" for="login_username">ชื่อผู้ใช้งาน (Username)</label>
          <input type="text" id="login_username" name="username" class="form-control" placeholder="เช่น admin หรือชื่อของคุณ" required autofocus>
        </div>
        <div class="form-group">
          <label class="form-label" for="login_password">รหัสผ่าน (Password)</label>
          <input type="password" id="login_password" name="password" class="form-control" placeholder="ระบุรหัสผ่านเพื่อเข้าใช้งาน" required>
        </div>
        <div class="form-group">
          <span class="form-label">Working environment</span>
          <div class="radio-group" role="radiogroup" aria-label="Working environment">
            <label class="radio-option"><input type="radio" name="internet" value="off" checked> No Internet / Internal (Default)</label>
            <label class="radio-option"><input type="radio" name="internet" value="on"> Internet</label>
          </div>
          <div class="form-help">The environment is fixed for this login session. No Internet / Internal permits approved internal services only; Internet uses a separate staging workspace. These environments do not share project files or chat history.</div>
        </div>
        <button type="submit" class="btn-submit">เข้าสู่ระบบ (Sign In)</button>
      </form>
    </div>

    ${ALLOW_REGISTRATION ? `<!-- 2. Form: สร้างบัญชีผู้ใช้ใหม่ -->
    <div id="pane-register" class="tab-pane" style="display: ${tab === 'register' ? 'block' : 'none'};">
      <form method="POST" action="/register">
        <div class="form-group">
          <label class="form-label" for="reg_username">ชื่อผู้ใช้งานใหม่ (New Username)</label>
          <input type="text" id="reg_username" name="username" class="form-control" placeholder="ตัวอักษรภาษาอังกฤษหรือตัวเลข (เช่น johndoe)" pattern="[a-zA-Z0-9_\-\.]{3,30}" title="ยาว 3-30 ตัวอักษร ใช้ได้เฉพาะ a-z, 0-9, _, -" required>
        </div>
        <div class="form-group">
          <label class="form-label" for="reg_password">รหัสผ่าน (Password)</label>
          <input type="password" id="reg_password" name="password" class="form-control" placeholder="รหัสผ่านอย่างน้อย 6 ตัวอักษร" minlength="6" required>
        </div>
        <div class="form-group">
          <label class="form-label" for="reg_confirm">ยืนยันรหัสผ่าน (Confirm Password)</label>
          <input type="password" id="reg_confirm" name="confirm_password" class="form-control" placeholder="กรอกรหัสผ่านอีกครั้ง" minlength="6" required>
        </div>
        <button type="submit" class="btn-submit">สร้างบัญชีผู้ใช้ใหม่ (Create Account)</button>
      </form>
    </div>

    ` : ''}
    <!-- 3. Form: เปลี่ยนรหัสผ่าน -->
    <div id="pane-change" class="tab-pane" style="display: ${tab === 'change' ? 'block' : 'none'};">
      <form method="POST" action="/change-password">
        <div class="form-group">
          <label class="form-label" for="chg_username">ชื่อผู้ใช้งาน (Username)</label>
          <input type="text" id="chg_username" name="username" class="form-control" placeholder="ระบุชื่อผู้ใช้งาน" required>
        </div>
        <div class="form-group">
          <label class="form-label" for="chg_old_password">รหัสผ่านเดิม (Current Password)</label>
          <input type="password" id="chg_old_password" name="old_password" class="form-control" placeholder="ระบุรหัสผ่านปัจจุบัน" required>
        </div>
        <div class="form-group">
          <label class="form-label" for="chg_new_password">รหัสผ่านใหม่ (New Password)</label>
          <input type="password" id="chg_new_password" name="new_password" class="form-control" placeholder="รหัสผ่านใหม่อย่างน้อย 6 ตัวอักษร" minlength="6" required>
        </div>
        <button type="submit" class="btn-submit">เปลี่ยนรหัสผ่าน (Update Password)</button>
      </form>
    </div>

    <div class="footer-note">
      ระบบสารสนเทศเฉพาะกิจองค์กร · รักษาความลับข้อมูลขั้นสูงสุด
    </div>
  </div>
</body>
</html>`;
}

const server = http.createServer((req, res) => {
  const parsedUrl = url.parse(req.url, true);

  // Handle Login Form Submission
  if (req.method === 'POST' && parsedUrl.pathname === '/login') {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      const params = new URLSearchParams(body);
      const username = params.get('username') ? params.get('username').trim().toLowerCase() : '';
      const password = params.get('password') ? params.get('password').trim() : '';
      const internet = normalizeInternetMode(params.get('internet'));

      USERS = loadUsers();
      if (USERS[username] && USERS[username] === password) {
        if (!getEnvironmentTarget(internet, username)) {
          res.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' });
          return res.end('No dedicated runtime provisioned for this identity and environment.');
        }
        if (!setUserInternetMode(username, internet)) {
          res.writeHead(500, { 'Content-Type': 'text/html; charset=utf-8' });
          return res.end(renderAuthPage({ tab: 'login', errorMsg: 'ไม่สามารถบันทึกนโยบาย Internet access ได้ กรุณาลองใหม่อีกครั้ง' }));
        }
        if (!auditEvent('login.success', username, internet)) { res.writeHead(503); return res.end('Audit storage unavailable.'); }
        const sessionId = crypto.randomBytes(24).toString('hex');
        SESSIONS.set(sessionId, { user: username, internet, created: Date.now() });

        // Create personal workspace folder for user if not exists
        try {
          fs.mkdirSync(`${USER_ROOT}/${username}`, { recursive: true });
        } catch (e) {}

        console.log(`[AUTH-PROXY] Successful login for user: ${username}`);
        const clientHost = req.headers['x-forwarded-host'] || req.headers.host || 'dsh.example.com';
        const target = getEnvironmentTarget(internet, username);
        getOrMintDshCookie(clientHost, target, (err, dshCookie) => {
          const domainAttr = getCookieDomain();
          const cookieHeaders = [`${COOKIE_NAME}=${sessionId}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400${domainAttr}${COOKIE_TRANSPORT}`];
          if (dshCookie) {
            cookieHeaders.push(`${dshCookie}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400${COOKIE_TRANSPORT}`);
          }
          res.writeHead(302, {
            'Set-Cookie': cookieHeaders,
            'Location': '/'
          });
          return res.end();
        });
      } else {
        auditEvent('login.denied', username, 'off');
        console.log(`[AUTH-PROXY] Failed login attempt for user: ${username}`);
        res.writeHead(401, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'login', errorMsg: 'ชื่อผู้ใช้งานหรือรหัสผ่านไม่ถูกต้อง กรุณาลองใหม่อีกครั้ง' }));
      }
    });
    return;
  }

  // Handle User Registration Form Submission
  if (req.method === 'POST' && parsedUrl.pathname === '/register') {
    if (!ALLOW_REGISTRATION) {
      res.writeHead(403, { 'Content-Type': 'text/plain; charset=utf-8' });
      return res.end('Self-registration is disabled. Contact the pilot administrator.');
    }
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      const params = new URLSearchParams(body);
      const username = params.get('username') ? params.get('username').trim().toLowerCase() : '';
      const password = params.get('password') ? params.get('password').trim() : '';
      const confirmPassword = params.get('confirm_password') ? params.get('confirm_password').trim() : '';

      if (!username || !/^[a-z0-9_\-\.]{3,30}$/.test(username)) {
        res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'register', errorMsg: 'ชื่อผู้ใช้งานต้องเป็นภาษาอังกฤษ/ตัวเลข ความยาว 3-30 ตัวอักษร' }));
      }

      if (!password || password.length < 6) {
        res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'register', errorMsg: 'รหัสผ่านต้องมีความยาวอย่างน้อย 6 ตัวอักษร' }));
      }

      if (password !== confirmPassword) {
        res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'register', errorMsg: 'รหัสผ่านและยืนยันรหัสผ่านไม่ตรงกัน กรุณาตรวจสอบอีกครั้ง' }));
      }

      USERS = loadUsers();
      if (USERS[username]) {
        res.writeHead(409, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'register', errorMsg: `ชื่อผู้ใช้งาน "${username}" มีอยู่ในระบบแล้ว กรุณาใช้ชื่ออื่นหรือเข้าสู่ระบบ` }));
      }

      USERS[username] = password;
      if (saveUsers(USERS)) {
        try {
          fs.mkdirSync(`${USER_ROOT}/${username}`, { recursive: true });
        } catch (e) {}
        console.log(`[AUTH-PROXY] Successfully registered new user: ${username}`);
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'login', successMsg: `สร้างบัญชี "${username}" เรียบร้อยแล้ว สามารถเข้าสู่ระบบได้ทันที` }));
      } else {
        res.writeHead(500, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'register', errorMsg: 'เกิดข้อผิดพลาดในการบันทึกข้อมูล กรุณาลองใหม่อีกครั้ง' }));
      }
    });
    return;
  }

  // Handle Password Change Form Submission
  if (req.method === 'POST' && parsedUrl.pathname === '/change-password') {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      const params = new URLSearchParams(body);
      const username = params.get('username') ? params.get('username').trim().toLowerCase() : '';
      const oldPassword = params.get('old_password') ? params.get('old_password').trim() : '';
      const newPassword = params.get('new_password') ? params.get('new_password').trim() : '';

      if (!username || !oldPassword || !newPassword) {
        res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'change', errorMsg: 'กรุณากรอกข้อมูลให้ครบทุกช่อง' }));
      }

      if (newPassword.length < 6) {
        res.writeHead(400, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'change', errorMsg: 'รหัสผ่านใหม่ต้องมีความยาวอย่างน้อย 6 ตัวอักษร' }));
      }

      USERS = loadUsers();
      if (!USERS[username] || USERS[username] !== oldPassword) {
        res.writeHead(401, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'change', errorMsg: 'ชื่อผู้ใช้งานหรือรหัสผ่านเดิมไม่ถูกต้อง' }));
      }

      USERS[username] = newPassword;
      if (saveUsers(USERS)) {
        console.log(`[AUTH-PROXY] Successfully changed password for user: ${username}`);
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'login', successMsg: `เปลี่ยนรหัสผ่านสำหรับผู้ใช้ "${username}" สำเร็จแล้ว กรุณาเข้าสู่ระบบด้วยรหัสผ่านใหม่` }));
      } else {
        res.writeHead(500, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'change', errorMsg: 'เกิดข้อผิดพลาดในการบันทึกรหัสผ่านใหม่ กรุณาลองใหม่อีกครั้ง' }));
      }
    });
    return;
  }

  // Handle Logout
  if (parsedUrl.pathname === '/logout') {
    for (const c of (req.headers.cookie || '').split(';').map(v => v.trim())) {
      for (const name of [COOKIE_NAME, 'dsh_auth']) {
        if (c.startsWith(`${name}=`)) {
          const sid = c.substring(name.length + 1);const s = SESSIONS.get(sid);
          if (s) auditEvent('logout', s.user, s.internet);
          SESSIONS.delete(sid);
        }
      }
    }
    const domainAttr = getCookieDomain();
    res.writeHead(302, {
      'Set-Cookie': `${COOKIE_NAME}=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; SameSite=Lax${domainAttr}${COOKIE_TRANSPORT}`,
      'Location': '/login'
    });
    return res.end();
  }

  // Check Session Cookie
  let authenticated = false;
  let sessionUser = null;
  let activeSession = null;
  const cookieHeader = req.headers.cookie;
  if (cookieHeader) {
    const cookies = cookieHeader.split(';').map(c => c.trim());
    for (const c of cookies) {
      if (c.startsWith(`${COOKIE_NAME}=`)) {
        const sid = c.substring(`${COOKIE_NAME}=`.length);
        if (SESSIONS.has(sid)) {
          authenticated = true;
          activeSession = SESSIONS.get(sid);
          sessionUser = activeSession.user;
          break;
        }
      }
      if (!authenticated && COOKIE_NAME !== 'dsh_auth' && c.startsWith('dsh_auth=')) {
        const sid = c.substring('dsh_auth='.length);
        if (SESSIONS.has(sid)) {
          authenticated = true;
          activeSession = SESSIONS.get(sid);
          sessionUser = activeSession.user;
          break;
        }
      }
    }
  }

  if (!authenticated) {
    const tab = parsedUrl.query.tab || 'login';
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    return res.end(renderAuthPage({ tab }));
  }

  // Reserve admin routes before any app forwarding or environment lookup.
  if (parsedUrl.pathname === '/admin' || parsedUrl.pathname === '/api/admin/summary' || parsedUrl.pathname === '/api/admin/audit') {
    const headers = { 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
      'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer' };
    if (!ADMIN_USERS.has(sessionUser)) { auditEvent('admin.denied', sessionUser, activeSession.internet); res.writeHead(403, headers); return res.end('Administrator access required.'); }
    if (req.method !== 'GET') { res.writeHead(405, { ...headers, Allow: 'GET' }); return res.end('Read-only endpoint.'); }
    const api = parsedUrl.pathname !== '/admin';
    res.writeHead(200, { ...headers, 'Content-Type': api ? 'application/json; charset=utf-8' : 'text/html; charset=utf-8' });
    return res.end(api ? JSON.stringify(parsedUrl.pathname.endsWith('/audit') ? {events:recentAudit()} : adminSummary()) : renderAdminDashboard());
  }
  const internetMode = normalizeInternetMode(activeSession && activeSession.internet);
  const environmentTarget = getEnvironmentTarget(internetMode, sessionUser);
  if (!environmentTarget) {
    res.writeHead(403);
    return res.end('Dedicated runtime is not provisioned.');
  }
  bindAuthenticatedProxyIdentity(req, sessionUser, internetMode);

  if (req.method === 'GET' && parsedUrl.pathname === '/api/auth/session') {
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
    return res.end(JSON.stringify({ user: sessionUser, internet: internetMode, environment: environmentTarget.name }));
  }

  // Convenient Terminal Shortcuts (/terminal, /term)
  if (parsedUrl.pathname === '/terminal' || parsedUrl.pathname === '/term') {
    res.writeHead(302, { 'Location': '/proxy/terminal/' });
    return res.end();
  }

  // Dynamic App Gateway (Option 1 Subdomain or Option 2 Path Proxy); only reachable after login
  if (!auditEvent('runtime.http', sessionUser, internetMode)) { res.writeHead(503); return res.end('Audit storage unavailable.'); }
  const incomingHost = req.headers['x-forwarded-host'] || req.headers.host || '';
  const appTarget = parseAppTarget(incomingHost, req.url);
  if (appTarget && appTarget.port) {
    return forwardToLocalApp(appTarget.port, appTarget.targetPath, req, res, environmentTarget.host);
  }

  // If authenticated, proxy request to DSH internal port 3081
  const token = getDshToken();

  // Ensure upstream DSH authentication cookie is established via internal token exchange
  function forwardToDsh(dshCookie) {
    const proxyHeaders = { ...req.headers };
    // Preserve client Host header (dsh.example.com) to satisfy trustedHosts and Origin checks
    const clientHost = req.headers['x-forwarded-host'] || req.headers.host || 'dsh.example.com';
    proxyHeaders['host'] = clientHost;
    proxyHeaders['x-dsh-user'] = sessionUser;
    proxyHeaders['x-dsh-internet-access'] = internetMode;
    // Request an uncompressed document so the authenticated UI can receive the
    // enterprise logout control without modifying the upstream DSH package.
    delete proxyHeaders['accept-encoding'];

    if (dshCookie) {
      const existingCookies = req.headers.cookie ? req.headers.cookie.split(';').map(c => c.trim()) : [];
      // Filter out any stale dsh-auth cookies and append current valid upstream cookie
      const filtered = existingCookies.filter(c => !c.startsWith('dsh-auth-'));
      filtered.push(dshCookie);
      proxyHeaders['cookie'] = filtered.join('; ');
    }

    const proxyReq = http.request({
      host: environmentTarget.host,
      port: environmentTarget.port,
      path: req.url,
      method: req.method,
      headers: proxyHeaders
    }, (proxyRes) => {
      // If upstream returns a redirect to / and we already passed a valid cookie, avoid client redirect storm
      const resHeaders = { ...proxyRes.headers };
      const isHtml = resHeaders['content-type'] && resHeaders['content-type'].includes('text/html');
      if (isHtml) {
        resHeaders['cache-control'] = 'no-cache, no-store, must-revalidate';
        resHeaders['pragma'] = 'no-cache';
        resHeaders['expires'] = '0';
        delete resHeaders['content-length'];
        delete resHeaders['content-encoding'];
        delete resHeaders['transfer-encoding'];
      }
      if (!isHtml) {
        res.writeHead(proxyRes.statusCode, resHeaders);
        return proxyRes.pipe(res);
      }

      const chunks = [];
      proxyRes.on('data', chunk => chunks.push(chunk));
      proxyRes.on('end', () => {
        const body = injectLogoutControl(Buffer.concat(chunks).toString('utf8'), ADMIN_USERS.has(sessionUser));
        resHeaders['content-length'] = Buffer.byteLength(body);
        res.writeHead(proxyRes.statusCode, resHeaders);
        res.end(body);
      });
    });

    proxyReq.on('error', (err) => {
      console.error('[AUTH-PROXY] Forward error:', err.message);
      res.writeHead(502, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Gateway Error: ไม่สามารถเชื่อมต่อบริการ DSH ภายในได้ กรุณารอสักครู่');
    });

    req.pipe(proxyReq);
  }

  const clientHost = req.headers['x-forwarded-host'] || req.headers.host || 'dsh.example.com';
  getOrMintDshCookie(clientHost, environmentTarget, (err, dshCookie) => {
    forwardToDsh(dshCookie);
  });
});

// Handle WebSocket Upgrades
server.on('upgrade', (req, socket, head) => {
  let authenticated = false;
  let activeSession = null;
  const cookieHeader = req.headers.cookie;
  if (cookieHeader) {
    const cookies = cookieHeader.split(';').map(c => c.trim());
    for (const c of cookies) {
      if (c.startsWith(`${COOKIE_NAME}=`)) {
        const sid = c.substring(`${COOKIE_NAME}=`.length);
        if (SESSIONS.has(sid)) {
          authenticated = true;
          activeSession = SESSIONS.get(sid);
          break;
        }
      }
      if (!authenticated && COOKIE_NAME !== 'dsh_auth' && c.startsWith('dsh_auth=')) {
        const sid = c.substring('dsh_auth='.length);
        if (SESSIONS.has(sid)) {
          authenticated = true;
          activeSession = SESSIONS.get(sid);
          break;
        }
      }
    }
  }

  if (!authenticated) {
    socket.destroy();
    return;
  }

  const internetMode = normalizeInternetMode(activeSession && activeSession.internet);
  const environmentTarget = getEnvironmentTarget(internetMode, activeSession.user);
  if (!environmentTarget) return socket.destroy();
  bindAuthenticatedProxyIdentity(req, activeSession.user, internetMode);

  // Dynamic App Gateway for WebSockets (e.g. Streamlit, Vite HMR, Next.js); only reachable after login
  const incomingHost = req.headers['x-forwarded-host'] || req.headers.host || '';
  const appTarget = parseAppTarget(incomingHost, req.url);
  if (appTarget && appTarget.port) {
    if (!auditEvent(appTarget.port === 7681 ? 'terminal.open' : 'application.websocket', activeSession.user, internetMode)) return socket.destroy();
    return forwardWebSocketToLocalApp(appTarget.port, appTarget.targetPath, req, socket, head, environmentTarget.host);
  }

  const clientHost = req.headers['x-forwarded-host'] || req.headers.host || 'dsh.example.com';
  getOrMintDshCookie(clientHost, environmentTarget, (err, dshCookie) => {
    // Reconstruct HTTP upgrade request buffer to guarantee dsh-auth cookie is included
    const rawHeaders = req.rawHeaders;
    let hasDshAuthInCookie = false;
    let cookieIdx = -1;
    for (let i = 0; i < rawHeaders.length; i += 2) {
      if (rawHeaders[i].toLowerCase() === 'cookie') {
        cookieIdx = i;
        if (rawHeaders[i + 1].includes('dsh-auth-')) {
          hasDshAuthInCookie = true;
        }
      }
    }

    let upgradeReqText = `${req.method} ${req.url} HTTP/${req.httpVersion}\r\n`;
    for (let i = 0; i < rawHeaders.length; i += 2) {
      const headerKey = rawHeaders[i];
      let headerVal = rawHeaders[i + 1];
      if (headerKey.toLowerCase() === 'host') {
        headerVal = clientHost;
      }
      if (headerKey.toLowerCase() === 'cookie' && dshCookie && !hasDshAuthInCookie) {
        headerVal = headerVal ? `${headerVal}; ${dshCookie}` : dshCookie;
      }
      upgradeReqText += `${headerKey}: ${headerVal}\r\n`;
    }
    if (cookieIdx === -1 && dshCookie) {
      upgradeReqText += `Cookie: ${dshCookie}\r\n`;
    }
    upgradeReqText += `\r\n`;

    const net = require('net');
    const targetSocket = net.connect(environmentTarget.port, environmentTarget.host, () => {
      targetSocket.write(upgradeReqText);
      if (head && head.length > 0) {
        targetSocket.write(head);
      }
      socket.pipe(targetSocket);
      targetSocket.pipe(socket);
    });

    targetSocket.on('error', () => {
      socket.destroy();
    });
  });
});

server.listen(PROXY_PORT, '0.0.0.0', () => {
  console.log(`[AUTH-PROXY] Enterprise DSH Auth Gate running on port ${PROXY_PORT}; secure=${ENVIRONMENT_TARGETS.off.host}:${ENVIRONMENT_TARGETS.off.port}; internet=${ENVIRONMENT_TARGETS.on.host}:${ENVIRONMENT_TARGETS.on.port}`);
});
