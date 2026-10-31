// Real HTTP and upgrade forwarding with mixed-case duplicate attacker headers.
const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const http = require('http');
const net = require('net');
const {spawn} = require('child_process');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-identity-'));
const backendPort = 39481, gatewayPort = 39480;
const own = req => ({user: req.headers['x-dsh-user'], mode: req.headers['x-dsh-internet-access'],
  count: req.rawHeaders.filter((v, i) => i % 2 === 0 && v.toLowerCase() === 'x-dsh-user').length});
const backend = http.createServer((req, res) => { res.writeHead(200, {'content-type': 'application/json'}); res.end(JSON.stringify(own(req))); });
backend.on('upgrade', (req, socket) => socket.end('HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n\r\n' + JSON.stringify(own(req))));
function httpRequest(method, requestPath, body = '', cookie = '', extra = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request({host: '127.0.0.1', port: gatewayPort, method, path: requestPath,
      headers: {host: 'dsh.test.local', cookie, 'content-type': 'application/x-www-form-urlencoded',
        'content-length': Buffer.byteLength(body), ...extra}}, res => {
      let text = ''; res.on('data', b => text += b);
      res.on('end', () => resolve({text, status: res.statusCode, cookie: (res.headers['set-cookie'] || [])[0]?.split(';')[0]}));
    }); req.on('error', reject); req.end(body);
  });
}
function upgrade(requestPath, cookie) {
  return new Promise((resolve, reject) => {
    let text = '';
    const s = net.connect(gatewayPort, '127.0.0.1', () => s.write(
      `GET ${requestPath} HTTP/1.1\r\nHost: dsh.test.local\r\nCookie: ${cookie}\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nX-DSH-User: bob\r\nx-dsh-user: mallory\r\nX-DSH-Internet-Access: on\r\n\r\n`));
    s.setTimeout(5000, () => s.destroy(new Error('Upgrade test timeout')));
    s.on('data', b => text += b); s.on('error', reject);
    s.on('end', () => { try { resolve(JSON.parse(text.split('\r\n\r\n')[1])); } catch (e) { reject(e); } });
  });
}
(async () => {
  fs.writeFileSync(path.join(root, 'users.json'), JSON.stringify({alice: 'synthetic-unit-password'}));
  await new Promise(resolve => backend.listen(backendPort, '127.0.0.1', resolve));
  const gateway = spawn(process.execPath, [process.env.DSH_IDENTITY_GATEWAY_SOURCE || path.join(__dirname, '../scripts/auth_proxy.js')], {env: {...process.env,
    PORT: String(gatewayPort), WORKSPACE_ROOT: root, DSH_USER_STORE_PATH: path.join(root, 'users.json'),
    DSH_USER_SETTINGS_PATH: path.join(root, 'settings.json'), DSH_OFFLINE_HOST: '127.0.0.1',
    DSH_OFFLINE_PORT: String(backendPort), DSH_ONLINE_PORT: String(backendPort),
    DSH_TRUSTED_HOST: 'dsh.test.local', DSH_COOKIE_SECURE: 'false'}, stdio: ['ignore', 'pipe', 'pipe']});
  try {
    let ready = false;
    for (let i = 0; i < 80; i++) { try { await httpRequest('GET', '/login'); ready = true; break; } catch { await new Promise(r => setTimeout(r, 50)); } }
    assert(ready);
    const login = await httpRequest('POST', '/login', 'username=alice&password=synthetic-unit-password&internet=off');
    assert.equal(login.status, 302);
    for (const route of ['/identity', `/proxy/${backendPort}/identity`]) {
      const response = await httpRequest('GET', route, '', login.cookie, {'X-DSH-User': 'bob', 'x-dsh-user': 'mallory', 'x-dsh-internet-access': 'on'});
      assert.deepEqual(JSON.parse(response.text), {user: 'alice', mode: 'off', count: 1});
    }
    for (const route of ['/identity', `/proxy/${backendPort}/identity`]) {
      assert.deepEqual(await upgrade(route, login.cookie), {user: 'alice', mode: 'off', count: 1});
    }
    for(const name of ['test_session_store','test_gateway_socket_reset','test_persistent_sessions','test_legacy_owner_policy']) {
      require('child_process').execFileSync(process.execPath,[path.join(__dirname,name+'.js')],{stdio:'inherit'});
    }
    console.log('Authenticated identity replaces forged/duplicate headers across default/custom HTTP and WebSocket carriers');
  } finally {
    gateway.kill(); await new Promise(resolve => gateway.once('exit', resolve));
    await new Promise(resolve => backend.close(resolve));
    fs.rmSync(root, {recursive: true, force: true});
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
