const assert = require('assert');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-route-'));
const users = path.join(root, '.user_auth.json');
fs.writeFileSync(users, JSON.stringify({ alice: 'secret1' }));

function backend(name) {
  return http.createServer((req, res) => {
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
  const gateway = spawn(process.execPath, [path.join(__dirname, '..', 'scripts', 'auth_proxy.js')], {
    env: {
      ...process.env,
      PORT: String(gatewayPort),
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
    const offLogin = await request(gatewayPort, 'POST', '/login', 'username=alice&password=secret1&internet=off');
    const offCookie = offLogin.headers['set-cookie'][0].split(';')[0];
    const offResult = JSON.parse((await request(gatewayPort, 'GET', '/probe', '', offCookie)).body);
    assert.deepEqual(offResult, { backend: 'secure-pool', environment: 'off' });

    const onLogin = await request(gatewayPort, 'POST', '/login', 'username=alice&password=secret1&internet=on');
    const onCookie = onLogin.headers['set-cookie'][0].split(';')[0];
    const onResult = JSON.parse((await request(gatewayPort, 'GET', '/probe', '', onCookie)).body);
    assert.deepEqual(onResult, { backend: 'internet-pool', environment: 'on' });

    const sticky = JSON.parse((await request(gatewayPort, 'GET', '/probe', '', offCookie)).body);
    assert.equal(sticky.backend, 'secure-pool');
    console.log('environment routing and session stickiness tests passed');
  } finally {
    gateway.kill();
    secure.close();
    internet.close();
    fs.rmSync(root, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
