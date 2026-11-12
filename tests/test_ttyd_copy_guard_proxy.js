const assert = require('assert');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');
const zlib = require('zlib');
const { spawn } = require('child_process');
const { hashPassword } = require('../scripts/password_store.js');

// End to end: login, GET /proxy/terminal/ through the real gateway to a fake ttyd on 127.0.0.1:7681. The page arrives with the guard inserted and correct length;
// non-HTML ttyd responses are untouched; DSH_TTYD_COPY_ON_SELECT=1 keeps the upstream page byte for byte.
const PAGE = '<!DOCTYPE html><html><head><meta charset="UTF-8"><title>ttyd</title></head><body><script>/* bundle */</script></body></html>';

function request(port, method, requestPath, headers = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port, method, path: requestPath, headers: { host: 'dsh.test.local', ...headers } }, (res) => {
      const chunks = []; res.on('data', (c) => chunks.push(c)); res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks) }));
    });
    req.on('error', reject); req.end();
  });
}
function login(port) {
  return new Promise((resolve, reject) => {
    const body = 'username=alice&password=secret1&application=dsh';
    const req = http.request({ host: '127.0.0.1', port, method: 'POST', path: '/login', headers: { host: 'dsh.test.local', 'content-type': 'application/x-www-form-urlencoded', 'content-length': Buffer.byteLength(body) } }, (res) => {
      res.resume(); res.on('end', () => resolve((res.headers['set-cookie'] || []).map((c) => c.split(';')[0]).join('; ')));
    });
    req.on('error', reject); req.end(body);
  });
}

async function withGateway(port, env, fn) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-copyguard-'));
  const users = path.join(root, '.user_auth.json');
  fs.writeFileSync(users, JSON.stringify({ alice: { ...hashPassword('secret1'), internetAllowed: false } }));
  const token = path.join(root, 'token'); fs.writeFileSync(token, 'tok-aaaaaaaaaaaaaaaaaaaaaaaa');
  const gateway = spawn(process.execPath, [path.join(__dirname, '..', 'scripts', 'auth_proxy.js')], { env: { ...process.env, PORT: String(port), DSH_ALLOW_REGISTRATION: 'false',
    DSH_OFFLINE_TOKEN_FILE: token, DSH_ONLINE_TOKEN_FILE: token, DSH_USER_STORE_PATH: users, DSH_USER_SETTINGS_PATH: path.join(root, '.user_settings.json'), WORKSPACE_ROOT: root,
    DSH_COOKIE_NAME: 'copyguard_auth', DSH_OFFLINE_HOST: '127.0.0.1', DSH_OFFLINE_PORT: '1', DSH_ONLINE_HOST: '127.0.0.1', DSH_ONLINE_PORT: '1', ...env }, stdio: ['ignore', 'pipe', 'pipe'] });
  try {
    for (let i = 0; i < 60; i += 1) { try { await request(port, 'GET', '/login'); break; } catch (_) { await new Promise((r) => setTimeout(r, 50)); } }
    await fn();
  } finally { gateway.kill(); }
}

(async () => {
  const seen = [];
  const ttyd = http.createServer((req, res) => {
    seen.push({ url: req.url, acceptEncoding: req.headers['accept-encoding'] });
    if (req.url === '/') { const gz = zlib.gzipSync(PAGE); const wantsGzip = /gzip/.test(req.headers['accept-encoding'] || ''); res.writeHead(200, { 'content-type': 'text/html', ...(wantsGzip ? { 'content-encoding': 'gzip' } : {}) }); return res.end(wantsGzip ? gz : PAGE); }
    if (req.url === '/token') { res.writeHead(200, { 'content-type': 'application/json' }); return res.end('{"token":""}'); }
    res.writeHead(404); res.end();
  });
  await new Promise((resolve, reject) => ttyd.listen(7681, '127.0.0.1', resolve).once('error', reject));
  try {
    await withGateway(39192, {}, async () => {
      const cookie = await login(39192); assert(cookie, 'login gives a session cookie');
      const page = await request(39192, 'GET', '/proxy/terminal/', { cookie, 'accept-encoding': 'gzip' });
      assert.equal(page.status, 200);
      const text = page.body.toString('utf8');
      assert(text.includes("document.execCommand=function(c){if(String(c).toLowerCase()==='copy')return false"), 'guard inserted into the page');
      assert(text.includes('/* bundle */') && text.startsWith('<!DOCTYPE html><html><head><script>'));
      assert(text.indexOf('<meta charset="UTF-8">') < 1024, 'the charset declaration stays within the first 1024 bytes');
      assert.equal(Number(page.headers['content-length']), page.body.length, 'content-length matches the edited page');
      assert(!page.headers['content-encoding'], 'the edited page is not compressed');
      assert.equal(seen[0].acceptEncoding, 'identity', 'the gateway asked ttyd for an uncompressed page');
      const token = await request(39192, 'GET', '/proxy/terminal/token', { cookie });
      assert.equal(token.body.toString(), '{"token":""}', 'other ttyd responses pass through untouched');
    });
    await withGateway(39193, { DSH_TTYD_COPY_ON_SELECT: '1' }, async () => {
      const cookie = await login(39193);
      const page = await request(39193, 'GET', '/proxy/terminal/', { cookie });
      assert.equal(page.body.toString('utf8'), PAGE, 'operator override keeps the upstream page byte for byte');
    });
    console.log('ttyd copy guard through the gateway: ok');
  } finally { ttyd.close(); }
})().catch((error) => { console.error(error); process.exit(1); });
