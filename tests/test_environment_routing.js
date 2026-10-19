const assert = require('assert');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');
const { hashPassword } = require('../scripts/password_store.js');

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-route-'));
const users = path.join(root, '.user_auth.json');
fs.writeFileSync(users, JSON.stringify({ alice: { ...hashPassword('secret1'), internetAllowed: false } }));
const secureToken = path.join(root, 'secure-token');
const internetToken = path.join(root, 'internet-token');
fs.writeFileSync(secureToken, 'secure-first');
fs.writeFileSync(internetToken, 'internet-first');

function backend(name) {
  return http.createServer((req, res) => {
    const token = fs.readFileSync(name === 'secure-pool' ? secureToken : internetToken, 'utf8');
    if (req.url.startsWith('/?token=')) {
      assert.equal(new URL(req.url, 'http://backend').searchParams.get('token'), token);
      res.writeHead(302, { 'set-cookie': `dsh-auth-${name}=${token}; Path=/; HttpOnly`, location: '/ui' });
      return res.end();
    }
    if (req.url === '/cookie-probe' && !(req.headers.cookie || '').includes(`dsh-auth-${name}=${token}`)) {
      res.writeHead(401); return res.end('stale backend cookie');
    }
    res.writeHead(200, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ backend: name, environment: req.headers['x-dsh-internet-access'] }));
  });
}

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
  throw new Error('gateway did not start');
}

(async () => {
  const secure = backend('secure-pool');
  const internet = backend('internet-pool');
  const securePort = 39181;
  const internetPort = 39182;
  const gatewayPort = 39180;
  await listen(secure, securePort);
  await listen(internet, internetPort);
  const gateway = spawn(process.execPath, [process.env.DSH_TEST_GATEWAY || path.join(__dirname, '..', 'scripts', 'auth_proxy.js')], {
    env: {
      ...process.env,
      PORT: String(gatewayPort),
      DSH_ALLOW_REGISTRATION: 'false',
      DSH_OFFLINE_TOKEN_FILE: secureToken,
      DSH_ONLINE_TOKEN_FILE: internetToken,
      DSH_USER_STORE_PATH: users,
      DSH_USER_SETTINGS_PATH: path.join(root, '.user_settings.json'),
      WORKSPACE_ROOT: root,
      DSH_COOKIE_NAME: 'route_auth',
      DSH_OFFLINE_HOST: '127.0.0.1',
      DSH_OFFLINE_PORT: String(securePort),
      DSH_ONLINE_HOST: '127.0.0.1',
      DSH_ONLINE_PORT: String(internetPort),
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  try {
    await waitReady(gatewayPort);
    const page = await request(gatewayPort, 'GET', '/login');
    assert(!page.body.includes('id="tab-register"'));
    assert(!page.body.includes('action="/register"'));
    assert(page.body.includes('id="login_application"'));
    assert(page.body.includes('<option value="jupyter">JupyterLab</option>'));
    const registration = await request(gatewayPort, 'POST', '/register', 'username=mallory&password=secret1&confirm_password=secret1');
    assert.equal(registration.status, 403);
    assert(!JSON.parse(fs.readFileSync(users, 'utf8')).mallory);
    for (const protectedPath of ['/proxy/8000/report', '/api/sessions', '/report.html']) {
      const anonymous = await request(gatewayPort, 'GET', protectedPath);
      assert.equal(anonymous.status, protectedPath.startsWith('/api/') ? 401 : 200);
      if(protectedPath.startsWith('/api/')) assert.equal(JSON.parse(anonymous.body).error,'AUTHENTICATION_REQUIRED');
      else assert(anonymous.body.includes('id="pane-login"'));
      assert(!anonymous.body.includes('secure-pool'));
    }
    const offLogin = await request(gatewayPort, 'POST', '/login', 'username=alice&password=secret1&internet=off');
    const offCookie = offLogin.headers['set-cookie'][0].split(';')[0];
    assert.equal(offLogin.headers.location, '/');
    for (const [application, location] of [['terminal','/terminal'],['jupyter','/proxy/8888/lab']]) {
      const launch = await request(gatewayPort, 'POST', '/login', 'username=alice&password=secret1&internet=off&application='+application);
      assert.equal(launch.status,302);assert.equal(launch.headers.location,location);
      const session=launch.headers['set-cookie'][0].split(';')[0];
      assert.equal(JSON.parse((await request(gatewayPort,'GET','/probe','',session)).body).backend,'secure-pool');
    }
    const injected=await request(gatewayPort,'POST','/login','username=alice&password=secret1&application=https://evil.example');
    assert.equal(injected.status,400);assert(!injected.headers['set-cookie']);
    assert.equal((await request(gatewayPort,'GET','/jupyter','',offCookie)).headers.location,'/proxy/8888/lab');
    const offResult = JSON.parse((await request(gatewayPort, 'GET', '/probe', '', offCookie)).body);
    assert.deepEqual(offResult, { backend: 'secure-pool', environment: 'off' });

    const deniedInternet = await request(gatewayPort, 'POST', '/login', 'username=alice&password=secret1&internet=on');
    assert.equal(deniedInternet.status, 403);
    const approvedUsers = JSON.parse(fs.readFileSync(users, 'utf8'));
    approvedUsers.alice.internetAllowed = true;
    fs.writeFileSync(users, JSON.stringify(approvedUsers));
    const onLogin = await request(gatewayPort, 'POST', '/login', 'username=alice&password=secret1&internet=on');
    assert.equal(onLogin.status, 302);
    const onCookie = onLogin.headers['set-cookie'][0].split(';')[0];
    const onResult = JSON.parse((await request(gatewayPort, 'GET', '/probe', '', onCookie)).body);
    assert.deepEqual(onResult, { backend: 'internet-pool', environment: 'on' });

    const sticky = JSON.parse((await request(gatewayPort, 'GET', '/probe', '', offCookie)).body);
    assert.equal(sticky.backend, 'secure-pool');
    assert.equal((await request(gatewayPort, 'GET', '/cookie-probe', '', offCookie)).status, 200);
    fs.writeFileSync(secureToken, 'secure-second'); // Simulate backend restart.
    const afterRestart = await request(gatewayPort, 'GET', '/cookie-probe', '', offCookie);
    assert.equal(afterRestart.status, 200, 'Gateway must remint after backend token rotation');
    assert.equal(JSON.parse(afterRestart.body).backend, 'secure-pool');
    console.log('environment routing and session stickiness tests passed');
  } finally {
    gateway.kill();
    secure.close();
    internet.close();
    fs.rmSync(root, { recursive: true, force: true });
  }
})().then(() => {
  // Existing upstream and image pipelines already run this entry point.
  require('child_process').execFileSync(process.execPath,
    [path.join(__dirname, 'test_service_status_reader.js')], { stdio: 'inherit', timeout: 10000 });
  require('child_process').execFileSync(process.execPath,
    [path.join(__dirname, 'test_self_registration.js')], { stdio: 'inherit', timeout: 60000 });
  require('child_process').execFileSync(process.execPath,
    [path.join(__dirname, 'test_session_recovery.js')], { stdio: 'inherit', timeout: 60000 });
  require('child_process').execFileSync(process.execPath,
    [path.join(__dirname, 'test_app_links.js')], { stdio: 'inherit', timeout: 60000 });
}).catch(error => { console.error(error); process.exitCode = 1; });
