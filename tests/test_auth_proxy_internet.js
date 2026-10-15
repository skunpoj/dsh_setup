const assert = require('assert');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-auth-proxy-'));
const users = path.join(root, '.user_auth.json');
const settings = path.join(root, '.user_settings.json');
fs.writeFileSync(users, JSON.stringify({ alice: 'secret1' }));

const backend = http.createServer((req, res) => {
  if (req.url === '/ui') {
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
    return res.end('<!doctype html><html><body><main>DSH UI</main></body></html>');
  }
  res.writeHead(200, { 'content-type': 'application/json' });
  res.end(JSON.stringify({
    user: req.headers['x-dsh-user'] || null,
    internet: req.headers['x-dsh-internet-access'] || null,
  }));
});

function listen(server, port) {
  return new Promise((resolve, reject) => server.listen(port, '127.0.0.1', resolve).once('error', reject));
}

function request(port, method, requestPath, body = '', cookie = '') {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port, method, path: requestPath, headers: {
      host: 'dsh.test.local',
      ...(body ? { 'content-type': 'application/x-www-form-urlencoded', 'content-length': Buffer.byteLength(body) } : {}),
      ...(cookie ? { cookie } : {}),
    } }, res => {
      let data = '';
      res.on('data', chunk => { data += chunk; });
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: data }));
    });
    req.on('error', reject);
    req.end(body);
  });
}

async function waitReady(port) {
  for (let i = 0; i < 50; i += 1) {
    try { await request(port, 'GET', '/login'); return; } catch (_) {}
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw new Error('auth proxy did not start');
}

(async () => {
  const backendPort = 39081;
  const proxyPort = 39080;
  await listen(backend, backendPort);
  const proxy = spawn(process.execPath, [path.join(__dirname, '..', 'scripts', 'auth_proxy.js')], {
    env: { ...process.env, PORT: String(proxyPort), DSH_PORT: String(backendPort), DSH_USER_STORE_PATH: users,
      DSH_USER_SETTINGS_PATH: settings, WORKSPACE_ROOT: root, DSH_COOKIE_NAME: 'test_auth' },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  try {
    await waitReady(proxyPort);
    const page = await request(proxyPort, 'GET', '/login');
    assert.equal(page.status, 200);
    assert.match(page.body, /name="internet" value="off" checked/);

    const denied = await request(proxyPort, 'POST', '/login', 'username=alice&password=wrong&internet=on');
    assert.equal(denied.status, 401);
    assert.equal(fs.existsSync(settings), false);

    const offLogin = await request(proxyPort, 'POST', '/login', 'username=alice&password=secret1');
    assert.equal(offLogin.status, 302);
    const offCookie = offLogin.headers['set-cookie'][0].split(';')[0];
    assert.deepEqual(JSON.parse(fs.readFileSync(settings, 'utf8')).alice, { internet: 'off' });
    const offSession = await request(proxyPort, 'GET', '/api/auth/session', '', offCookie);
    assert.deepEqual(JSON.parse(offSession.body), { user: 'alice', internet: 'off' });

    const onLogin = await request(proxyPort, 'POST', '/login', 'username=alice&password=secret1&internet=on');
    assert.equal(onLogin.status, 302);
    const onCookie = onLogin.headers['set-cookie'][0].split(';')[0];
    assert.deepEqual(JSON.parse(fs.readFileSync(settings, 'utf8')).alice, { internet: 'on' });
    const forwarded = await request(proxyPort, 'GET', '/probe', '', onCookie);
    assert.deepEqual(JSON.parse(forwarded.body), { user: 'alice', internet: 'on' });

    const ui = await request(proxyPort, 'GET', '/ui', '', onCookie);
    assert.equal(ui.status, 200);
    assert.match(ui.body, /id="dsh-enterprise-logout"/);
    assert.match(ui.body, /href="\/logout"/);
    assert.match(ui.body, /ออกจากระบบ \/ Logout/);
    assert.equal((ui.body.match(/id="dsh-enterprise-logout"/g) || []).length, 1);

    const logout = await request(proxyPort, 'GET', '/logout', '', onCookie);
    assert.equal(logout.status, 302);
    assert.equal(logout.headers.location, '/login');
    assert.match(logout.headers['set-cookie'][0], /^test_auth=;/);
    const afterLogout = await request(proxyPort, 'GET', '/api/auth/session', '', onCookie);
    assert.equal(afterLogout.status, 200);
    assert.match(afterLogout.body, /เข้าสู่ระบบ/);
    console.log('auth proxy internet policy tests passed');
  } finally {
    proxy.kill();
    backend.close();
    fs.rmSync(root, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
