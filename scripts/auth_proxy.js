const http = require('http');
const url = require('url');
const fs = require('fs');
const crypto = require('crypto');

const PROXY_PORT = 3080;
const DSH_TARGET_PORT = 3081;
const DSH_TARGET_HOST = '127.0.0.1';
const USER_STORE_PATH = '/workspace/users/.user_auth.json';

// In-memory sessions
const SESSIONS = new Map();
const cachedDshAuthCookies = new Map();

// --- DYNAMIC APP GATEWAY HELPERS (OPTION 1 & OPTION 2) ---
function resolvePortAlias(alias) {
  try {
    const portsPath = '/workspace/.ports.json';
    if (fs.existsSync(portsPath)) {
      const mapping = JSON.parse(fs.readFileSync(portsPath, 'utf8'));
      if (mapping && mapping[alias]) {
        return parseInt(mapping[alias], 10);
      }
    }
  } catch (e) {
    console.error('[AUTH-PROXY] Error reading .ports.json:', e.message);
  }
  return null;
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

function forwardToLocalApp(targetPort, targetPath, req, res) {
  const proxyHeaders = { ...req.headers };
  proxyHeaders['host'] = `127.0.0.1:${targetPort}`;
  proxyHeaders['x-forwarded-host'] = req.headers.host;
  proxyHeaders['x-forwarded-proto'] = req.headers['x-forwarded-proto'] || 'https';

  const proxyReq = http.request({
    host: '127.0.0.1',
    port: targetPort,
    path: targetPath,
    method: req.method,
    headers: proxyHeaders
  }, (proxyRes) => {
    res.writeHead(proxyRes.statusCode, proxyRes.headers);
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

function forwardWebSocketToLocalApp(targetPort, targetPath, req, socket, head) {
  const rawHeaders = req.rawHeaders;
  let upgradeReqText = `${req.method} ${targetPath} HTTP/${req.httpVersion}\r\n`;
  for (let i = 0; i < rawHeaders.length; i += 2) {
    const headerKey = rawHeaders[i];
    let headerVal = rawHeaders[i + 1];
    if (headerKey.toLowerCase() === 'host') {
      headerVal = `127.0.0.1:${targetPort}`;
    }
    upgradeReqText += `${headerKey}: ${headerVal}\r\n`;
  }
  upgradeReqText += `\r\n`;

  const net = require('net');
  const targetSocket = net.connect(targetPort, '127.0.0.1', () => {
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

function getOrMintDshCookie(clientHost, callback) {
  const existing = cachedDshAuthCookies.get(clientHost);
  if (existing) {
    return callback(null, existing);
  }
  const token = getDshToken();
  if (!token) {
    return callback(new Error("No DSH launch token available"));
  }
  const authReq = http.request({
    host: DSH_TARGET_HOST,
    port: DSH_TARGET_PORT,
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
          cachedDshAuthCookies.set(clientHost, mintedCookie);
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
    fs.mkdirSync('/workspace/users', { recursive: true });
    fs.writeFileSync(USER_STORE_PATH, JSON.stringify(users, null, 2), 'utf8');
    return true;
  } catch (e) {
    console.error('[AUTH-PROXY] Failed to save user store:', e.message);
    return false;
  }
}

// Initialize user store if missing
let USERS = loadUsers();
if (!fs.existsSync(USER_STORE_PATH)) {
  saveUsers(USERS);
}

function getDshToken() {
  try {
    if (fs.existsSync('/tmp/dsh_token.txt')) {
      return fs.readFileSync('/tmp/dsh_token.txt', 'utf8').trim();
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
  <link href="https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap" rel="stylesheet">
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
      <div id="tab-register" class="auth-tab ${tab === 'register' ? 'active' : ''}" onclick="switchTab('register')">สร้างบัญชีผู้ใช้ใหม่</div>
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
        <button type="submit" class="btn-submit">เข้าสู่ระบบ (Sign In)</button>
      </form>
    </div>

    <!-- 2. Form: สร้างบัญชีผู้ใช้ใหม่ -->
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

      USERS = loadUsers();
      if (USERS[username] && USERS[username] === password) {
        const sessionId = crypto.randomBytes(24).toString('hex');
        SESSIONS.set(sessionId, { user: username, created: Date.now() });

        // Create personal workspace folder for user if not exists
        try {
          fs.mkdirSync(`/workspace/users/${username}`, { recursive: true });
        } catch (e) {}

        console.log(`[AUTH-PROXY] Successful login for user: ${username}`);
        const clientHost = req.headers['x-forwarded-host'] || req.headers.host || 'dsh.example.com';
        getOrMintDshCookie(clientHost, (err, dshCookie) => {
          const cookieHeaders = [`dsh_auth=${sessionId}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400`];
          if (dshCookie) {
            cookieHeaders.push(`${dshCookie}; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400`);
          }
          res.writeHead(302, {
            'Set-Cookie': cookieHeaders,
            'Location': '/'
          });
          return res.end();
        });
      } else {
        console.log(`[AUTH-PROXY] Failed login attempt for user: ${username}`);
        res.writeHead(401, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(renderAuthPage({ tab: 'login', errorMsg: 'ชื่อผู้ใช้งานหรือรหัสผ่านไม่ถูกต้อง กรุณาลองใหม่อีกครั้ง' }));
      }
    });
    return;
  }

  // Handle User Registration Form Submission
  if (req.method === 'POST' && parsedUrl.pathname === '/register') {
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
          fs.mkdirSync(`/workspace/users/${username}`, { recursive: true });
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

  // Check Session Cookie
  let authenticated = false;
  let sessionUser = null;
  const cookieHeader = req.headers.cookie;
  if (cookieHeader) {
    const cookies = cookieHeader.split(';').map(c => c.trim());
    for (const c of cookies) {
      if (c.startsWith('dsh_auth=')) {
        const sid = c.substring('dsh_auth='.length);
        if (SESSIONS.has(sid)) {
          authenticated = true;
          sessionUser = SESSIONS.get(sid).user;
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

  // Dynamic App Gateway (Option 1 Subdomain or Option 2 Path Proxy); only reachable after login
  const incomingHost = req.headers['x-forwarded-host'] || req.headers.host || '';
  const appTarget = parseAppTarget(incomingHost, req.url);
  if (appTarget && appTarget.port) {
    return forwardToLocalApp(appTarget.port, appTarget.targetPath, req, res);
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

    if (dshCookie) {
      const existingCookies = req.headers.cookie ? req.headers.cookie.split(';').map(c => c.trim()) : [];
      // Filter out any stale dsh-auth cookies and append current valid upstream cookie
      const filtered = existingCookies.filter(c => !c.startsWith('dsh-auth-'));
      filtered.push(dshCookie);
      proxyHeaders['cookie'] = filtered.join('; ');
    }

    const proxyReq = http.request({
      host: DSH_TARGET_HOST,
      port: DSH_TARGET_PORT,
      path: req.url,
      method: req.method,
      headers: proxyHeaders
    }, (proxyRes) => {
      // If upstream returns a redirect to / and we already passed a valid cookie, avoid client redirect storm
      res.writeHead(proxyRes.statusCode, proxyRes.headers);
      proxyRes.pipe(res);
    });

    proxyReq.on('error', (err) => {
      console.error('[AUTH-PROXY] Forward error:', err.message);
      res.writeHead(502, { 'Content-Type': 'text/plain; charset=utf-8' });
      res.end('Gateway Error: ไม่สามารถเชื่อมต่อบริการ DSH ภายในได้ กรุณารอสักครู่');
    });

    req.pipe(proxyReq);
  }

  const clientHost = req.headers['x-forwarded-host'] || req.headers.host || 'dsh.example.com';
  getOrMintDshCookie(clientHost, (err, dshCookie) => {
    forwardToDsh(dshCookie);
  });
});

// Handle WebSocket Upgrades
server.on('upgrade', (req, socket, head) => {
  let authenticated = false;
  const cookieHeader = req.headers.cookie;
  if (cookieHeader) {
    const cookies = cookieHeader.split(';').map(c => c.trim());
    for (const c of cookies) {
      if (c.startsWith('dsh_auth=')) {
        const sid = c.substring('dsh_auth='.length);
        if (SESSIONS.has(sid)) {
          authenticated = true;
          break;
        }
      }
    }
  }

  if (!authenticated) {
    socket.destroy();
    return;
  }

  // Dynamic App Gateway for WebSockets (e.g. Streamlit, Vite HMR, Next.js); only reachable after login
  const incomingHost = req.headers['x-forwarded-host'] || req.headers.host || '';
  const appTarget = parseAppTarget(incomingHost, req.url);
  if (appTarget && appTarget.port) {
    return forwardWebSocketToLocalApp(appTarget.port, appTarget.targetPath, req, socket, head);
  }

  const clientHost = req.headers['x-forwarded-host'] || req.headers.host || 'dsh.example.com';
  getOrMintDshCookie(clientHost, (err, dshCookie) => {
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
    const targetSocket = net.connect(DSH_TARGET_PORT, DSH_TARGET_HOST, () => {
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
  console.log(`[AUTH-PROXY] Enterprise DSH Auth Gate running on port ${PROXY_PORT} -> forwarding to ${DSH_TARGET_HOST}:${DSH_TARGET_PORT}`);
});
