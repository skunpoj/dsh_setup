'use strict';
const assert = require('assert/strict');
const fs = require('fs');
const path = require('path');
const os = require('os');
const http = require('http');
const crypto = require('crypto');
const { spawn } = require('child_process');
const { parts, range, readManifest, MAX_FILE } = require('../scripts/course_files');
const { publish } = require('../scripts/publish_course_bundle');
const hash = body => crypto.createHash('sha256').update(body).digest('hex');
function makeBundle(root, label) {
  fs.mkdirSync(root); fs.mkdirSync(path.join(root, 'media'));
  const files = { 'index.html': Buffer.from(`<script>window.courseInline=true</script><h1>${label}</h1>`),
    'media/lesson.mp4': Buffer.from(Array.from({ length: 512 }, (_, i) => i % 256)),
    'media/lesson.vtt': Buffer.from('WEBVTT\n\n00:00.000 --> 00:01.000\nFixture\n'),
    'reproduction.zip': Buffer.from('PK\x03\x04fixture-reproduction') };
  const manifest = { schema: 1, files: {} };
  for (const [name, data] of Object.entries(files)) {
    fs.writeFileSync(path.join(root, name), data, { mode: 0o444 });
    manifest.files[name] = { sha256: hash(data), bytes: data.length };
  }
  const raw = Buffer.from(JSON.stringify(manifest));
  fs.writeFileSync(path.join(root, '.course-manifest.json'), raw, { mode: 0o444 });
  fs.chmodSync(path.join(root, 'media'), 0o555); fs.chmodSync(root, 0o555);
  return { root, files, sha256: hash(raw) };
}
function request(port, method, uri, { cookie, host = 'dsh.test.local', body = '', headers = {} } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port, method, path: uri, headers: { host, ...headers,
      ...(cookie ? { cookie } : {}), ...(body ? { 'content-type': 'application/x-www-form-urlencoded', 'content-length': Buffer.byteLength(body) } : {}) } }, res => {
      const chunks = []; res.on('data', chunk => chunks.push(chunk));
      res.on('error', reject);
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks) }));
    }); req.on('error', reject); req.setTimeout(10000, () => req.destroy(Error('Fixture HTTP timeout: ' + method + ' ' + uri))); req.end(body);
  });
}
async function run() {
  for (const name of ['../secret.txt', '/a.mp4', 'a//b.mp4', 'a\\b.mp4', 'a\0.mp4', 'secret.env', '.course-manifest.json']) assert.throws(() => parts(name));
  assert.deepEqual(range('bytes=-5', 10), { start: 5, end: 9, partial: true });
  for (const value of ['bytes=10-', 'bytes=-0', 'bytes=5-1', 'bytes=0-1,3-4']) assert.throws(() => range(value, 10));
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-course-test-'));
  fs.chmodSync(root, 0o755);
  let proxy, backend;
  try {
    const dsh = makeBundle(path.join(root, 'dsh'), 'DSH fixture');
    const gpu = makeBundle(path.join(root, 'gpu'), 'GPU fixture');
    const auth = path.join(root, 'auth'); fs.mkdirSync(auth, { mode: 0o700 });
    const users = path.join(auth, 'users.json'); fs.writeFileSync(users, JSON.stringify({ alice: 'synthetic-password' }), { mode: 0o600 });
    const nonRootLinux = process.platform === 'linux' && process.getuid() === 0;
    if (nonRootLinux) { fs.chownSync(auth, 10001, 10001); fs.chownSync(users, 10001, 10001); }
    backend = http.createServer((req, res) => { res.writeHead(200); res.end('{}'); });
    await new Promise(resolve => backend.listen(0, '127.0.0.1', resolve));
    const portServer = http.createServer(); await new Promise(resolve => portServer.listen(0, '127.0.0.1', resolve));
    const port = portServer.address().port; await new Promise(resolve => portServer.close(resolve));
    proxy = spawn(process.execPath, [path.join(__dirname, '../scripts/auth_proxy.js')], { env: {
      ...Object.fromEntries(Object.entries(process.env).filter(([k]) => !/^(DSH_|GPU_COURSE|AUTH_|WORKSPACE_ROOT$)/.test(k))),
      PORT: String(port), DSH_TARGET_PORT: String(backend.address().port), DSH_SINGLE_USER: 'alice',
      DSH_USER_STORE_PATH: users, DSH_USER_SETTINGS_PATH: path.join(auth, 'settings.json'), WORKSPACE_ROOT: auth,
      DSH_TRUSTED_HOST: 'dsh.test.local', DSH_COOKIE_NAME: 'fixture_auth', DSH_COOKIE_DOMAIN: '.test.local',
      DSH_COURSE_ROOT: dsh.root, DSH_COURSE_MANIFEST_SHA256: dsh.sha256,
      GPU_COURSE_ROOT: gpu.root, GPU_COURSE_MANIFEST_SHA256: gpu.sha256, GPU_COURSE_HOST: 'gpu.test.local',
    }, ...(nonRootLinux ? { uid: 10001, gid: 10001 } : {}), stdio: ['ignore', 'pipe', 'pipe'] });
    let diagnostics = ''; proxy.stderr.on('data', chunk => { diagnostics += chunk; });
    for (let i = 0; ; i++) { try { await request(port, 'GET', '/login'); break; } catch { if (i > 60) throw Error(diagnostics || 'Proxy not ready'); await new Promise(r => setTimeout(r, 50)); } }
    for (const uri of ['/manual/course/', '/manual/course/media/lesson.mp4', '/manual/course/reproduction.zip', '/gpu-course/media/lesson.mp4']) {
      for (const method of ['GET', 'HEAD']) assert.equal((await request(port, method, uri)).status, 303);
    }
    assert.equal((await request(port, 'POST', '/login', { body: 'username=alice&password=wrong' })).status, 401);
    const login = await request(port, 'POST', '/login', { body: 'username=alice&password=synthetic-password' });
    assert.equal(login.status, 302); assert.match(login.headers['set-cookie'][0], /Domain=.test.local/);
    const cookie = login.headers['set-cookie'][0].split(';')[0];
    console.log('COURSE_FIXTURE_LOGIN_OK');
    if (process.platform !== 'linux' || process.getuid() !== 0) {
      assert.equal((await request(port, 'GET', '/manual/course/', { cookie })).status, 404);
      console.log('PASS auth integration; Linux descriptor positives intentionally not run on this OS/UID'); return;
    }
    const index = await request(port, 'GET', '/manual/course/', { cookie });
    assert.equal(index.status, 200); assert.deepEqual(index.body, dsh.files['index.html']);
    console.log('COURSE_FIXTURE_NONROOT_INDEX_OK');
    assert.match(index.headers['content-security-policy'], /media-src 'self' blob:/);
    assert.match(index.headers['content-security-policy'], /script-src 'self' 'unsafe-inline'/);
    assert.throws(() => readManifest({ root: dsh.root, sha256: '0'.repeat(64) }));
    const alias = path.join(root, 'alias'); fs.symlinkSync(dsh.root, alias);
    assert.throws(() => readManifest({ root: alias, sha256: dsh.sha256 }));
    assert.equal((await request(port, 'GET', '/gpu-course/', { cookie, host: 'gpu.test.local' })).body.toString().includes('GPU fixture'), true);
    assert.equal((await request(port, 'GET', '/gpu-course/', { cookie })).status, 404);
    assert.equal((await request(port, 'GET', '/manual/course/', { cookie, host: 'evil.test.local' })).status, 404);
    assert.equal((await request(port, 'GET', '/gpu-course', { cookie, host: 'gpu.test.local' })).headers.location, '/manual/course/');
    const uri = '/manual/course/media/lesson.mp4', bytes = dsh.files['media/lesson.mp4'];
    assert.deepEqual((await request(port, 'GET', uri, { cookie })).body, bytes);
    for (const [value, expected] of [['bytes=0-15', bytes.subarray(0, 16)], ['bytes=100-199', bytes.subarray(100, 200)], ['bytes=-16', bytes.subarray(-16)], ['bytes=500-', bytes.subarray(500)]]) {
      const partial = await request(port, 'GET', uri, { cookie, headers: { Range: value } });
      assert.equal(partial.status, 206); assert.deepEqual(partial.body, expected);
    }
    const head = await request(port, 'HEAD', uri, { cookie }); assert.equal(head.status, 200); assert.equal(head.body.length, 0); assert.equal(Number(head.headers['content-length']), bytes.length);
    for (const value of ['bytes=9999-', 'bytes=wrong', 'bytes=0-1,3-4']) assert.equal((await request(port, 'GET', uri, { cookie, headers: { Range: value } })).status, 416);
    assert.equal((await request(port, 'GET', uri, { cookie, headers: { Range: 'bytes=0-1', 'If-Range': '"other"' } })).status, 200);
    const zip = await request(port, 'GET', '/manual/course/reproduction.zip', { cookie });
    assert.equal(zip.headers['content-type'], 'application/zip'); assert.match(zip.headers['content-disposition'], /^attachment/);
    assert.equal((await request(port, 'GET', '/manual/course/media/lesson.vtt', { cookie })).headers['content-type'], 'text/vtt; charset=utf-8');
    for (const name of ['missing.mp4', '%2e%2e/secret.txt', 'media%5csecret.mp4', '.course-manifest.json']) assert.equal((await request(port, 'GET', '/manual/course/' + name, { cookie })).status, 404);
    const parent = path.join(root, 'published'); fs.mkdirSync(parent, { mode: 0o755 });
    const destination = path.join(parent, 'generation');
    const publication = publish({ source: gpu.root, sha256: gpu.sha256, destination });
    assert.equal(publication.files, 4);
    const repeated = publish({ source: gpu.root, sha256: gpu.sha256, destination });
    assert.equal(repeated.existing_generation_verified, true);
    assert.equal(repeated.bytes, publication.bytes);
    const publishedIndex = path.join(destination, 'index.html');
    const approvedIndex = fs.readFileSync(publishedIndex);
    fs.chmodSync(publishedIndex, 0o644); fs.writeFileSync(publishedIndex, 'corrupt'); fs.chmodSync(publishedIndex, 0o444);
    assert.throws(() => publish({ source: gpu.root, sha256: gpu.sha256, destination }));
    assert.equal(fs.readFileSync(publishedIndex, 'utf8'), 'corrupt');
    fs.chmodSync(publishedIndex, 0o644); fs.writeFileSync(publishedIndex, approvedIndex); fs.chmodSync(publishedIndex, 0o444);
    fs.chmodSync(destination, 0o755); fs.writeFileSync(path.join(destination, 'extra.txt'), 'extra', { mode: 0o444 }); fs.chmodSync(destination, 0o555);
    assert.throws(() => publish({ source: gpu.root, sha256: gpu.sha256, destination }));
    fs.chmodSync(destination, 0o755); fs.unlinkSync(path.join(destination, 'extra.txt')); fs.chmodSync(destination, 0o555);
    assert.equal(fs.statSync(path.join(destination, 'index.html')).nlink, 1);
    assert.equal(fs.statSync(destination).mode & 0o222, 0);
    console.log('COURSE_FIXTURE_PUBLISHER_AND_RANGES_OK');
    const media = path.join(dsh.root, 'media/lesson.mp4'); fs.chmodSync(media, 0o644); fs.writeFileSync(media, Buffer.alloc(bytes.length)); fs.chmodSync(media, 0o444);
    assert.equal((await request(port, 'GET', uri, { cookie })).status, 404); // cache invalidates by ctime identity.
    fs.chmodSync(path.join(dsh.root, 'media'), 0o755); fs.unlinkSync(media); fs.symlinkSync(path.join(gpu.root, 'media/lesson.mp4'), media); fs.chmodSync(path.join(dsh.root, 'media'), 0o555);
    assert.equal((await request(port, 'GET', uri, { cookie })).status, 404);
    fs.chmodSync(path.join(dsh.root, 'media'), 0o755); fs.unlinkSync(media); fs.linkSync(path.join(gpu.root, 'media/lesson.mp4'), media); fs.chmodSync(path.join(dsh.root, 'media'), 0o555);
    assert.equal((await request(port, 'GET', uri, { cookie })).status, 404);
    const account = JSON.parse(fs.readFileSync(users)); account.alice.disabled = true; fs.writeFileSync(users, JSON.stringify(account));
    assert.equal((await request(port, 'GET', '/gpu-course/', { cookie, host: 'gpu.test.local' })).status, 303);
    await request(port, 'GET', '/logout', { cookie }); assert.equal((await request(port, 'GET', '/manual/course/', { cookie })).status, 303);
    console.log(JSON.stringify({ actual_auth_proxy_login: true, gateway_uid: 10001, linux_descriptor_http: true, two_separate_project_roots: true, range_head_vtt_zip: true, hash_cache_invalidation_links_and_traversal_rejected: true, disabled_account_revoked: true, isolated_publisher: true, max_file_bytes: MAX_FILE, model_calls: 0 }));
  } finally {
    if (proxy && proxy.exitCode === null && proxy.signalCode === null) {
      await new Promise(resolve => { proxy.once('exit', resolve); proxy.kill(); });
    }
    if (backend) await new Promise(resolve => backend.close(resolve));
    // Only our uniquely-created fixture tree, never production storage.
    function writable(dir) { for (const item of fs.readdirSync(dir, { withFileTypes: true })) { const p = path.join(dir, item.name); if (item.isDirectory()) writable(p); else if (!item.isSymbolicLink()) fs.chmodSync(p, 0o644); } fs.chmodSync(dir, 0o755); }
    writable(root); fs.rmSync(root, { recursive: true, force: true });
  }
}
run().catch(error => { console.error(error); process.exitCode = 1; });
