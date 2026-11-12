const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const net = require('node:net');
const crypto = require('node:crypto');
const {spawn} = require('node:child_process');

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-manual-'));
const dir = path.join(root, 'manual');
const manifestPath = path.join(dir, 'manifest.json');
const files = {};
const skipped = [];
let child;
let port;
let checks = 0;
fs.mkdirSync(dir);
fs.writeFileSync(path.join(root, 'users.json'), '{}');

function entry(body) {
  return {bytes: body.length, sha256: crypto.createHash('sha256').update(body).digest('hex')};
}
function writeManifest() {
  fs.writeFileSync(manifestPath, JSON.stringify({files}));
}
function fixture(name, content) {
  const body = Buffer.from(content);
  const file = path.join(dir, name);
  fs.mkdirSync(path.dirname(file), {recursive: true});
  fs.writeFileSync(file, body);
  files[name] = entry(body);
  return body;
}
function request(route, method = 'GET', headers = {}) {
  return new Promise((resolve, reject) => {
    const call = http.request({hostname: '127.0.0.1', port, path: route, method, headers}, response => {
      const chunks = [];
      response.on('data', chunk => chunks.push(chunk));
      response.on('end', () => resolve({status: response.statusCode,
        bytes: Buffer.concat(chunks), headers: response.headers}));
    });
    call.on('error', reject);
    call.setTimeout(5000, () => call.destroy(Error('Fixture request timed out')));
    call.end();
  });
}
async function denied(route, method = 'GET', headers = {}) {
  const response = await request(route, method, headers);
  assert.equal(response.status, 404, route);
  assert(!response.bytes.includes('PRIVATE_ACCOUNT_CONTENT'));
  if (method === 'HEAD') assert.equal(response.bytes.length, 0);
  checks++;
}
async function main() {
  const reservation = net.createServer();
  await new Promise(resolve => reservation.listen(0, '127.0.0.1', resolve));
  port = reservation.address().port;
  await new Promise(resolve => reservation.close(resolve));
  const formats = {
    html: 'text/html; charset=utf-8', md: 'text/plain; charset=utf-8',
    json: 'application/json; charset=utf-8', png: 'image/png', svg: 'image/svg+xml',
    mp4: 'video/mp4', vtt: 'text/vtt; charset=utf-8', pdf: 'application/pdf',
    pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    txt: 'text/plain; charset=utf-8'
  };
  const bodies = {};
  for (const extension of Object.keys(formats)) bodies[extension] = fixture(`guide.${extension}`, `Synthetic ${extension} fixture`);
  const media = fixture('media/guide.mp4', Buffer.from(Array.from({length: 512}, (_, index) => index % 256)));
  fixture('empty.mp4', '');
  const privateBody = Buffer.from('PRIVATE_ACCOUNT_CONTENT');
  fs.writeFileSync(path.join(root, 'private.md'), privateBody);
  fixture('tampered.html', 'original');
  fs.writeFileSync(path.join(dir, 'tampered.html'), 'changed');
  fixture('oversized.txt', Buffer.alloc(8 * 1024 * 1024 + 1, 65));
  fixture('boundary.txt', Buffer.alloc(8 * 1024 * 1024, 66));
  writeManifest();
  child = spawn(process.execPath, [path.join(__dirname, '../scripts/auth_proxy.js')], {
    env: {...Object.fromEntries(Object.entries(process.env).filter(([key]) => !/^(DSH_|AUTH_|WORKSPACE_ROOT$)/.test(key))),
      PORT: String(port), DSH_MANUAL_DIR: dir,
      DSH_USER_STORE_PATH: path.join(root, 'users.json'), WORKSPACE_ROOT: root}, stdio: 'ignore'
  });
  let ready = false;
  for (let attempt = 0; attempt < 60; attempt++) {
    assert.equal(child.exitCode, null, 'Owned gateway exited before readiness');
    try { await request('/manual'); ready = true; break; }
    catch { await new Promise(resolve => setTimeout(resolve, 50)); }
  }
  assert(ready, 'Owned gateway did not start');
  for (const route of ['/manual', '/manual/']) {
    const redirect = await request(route);
    assert.equal(redirect.status, 302);
    assert.equal(redirect.headers.location, '/manual/DSH_USER_MANUAL.html');
    checks++;
  }
  // Empty account store and no cookies exercise the established public manual policy.
  for (const [extension, type] of Object.entries(formats)) {
    for (const method of ['GET', 'HEAD']) {
      const response = await request(`/manual/guide.${extension}`, method);
      assert.equal(response.status, 200);
      assert.equal(response.headers['content-type'], type);
      assert.equal(Number(response.headers['content-length']), bodies[extension].length);
      assert.deepEqual(response.bytes, method === 'HEAD' ? Buffer.alloc(0) : bodies[extension]);
      assert.equal(response.headers['x-content-type-options'], 'nosniff');
      assert.match(response.headers['content-security-policy'], /media-src 'self' data: blob:/);
      checks++;
    }
  }
  for (const [range, start, end] of [['bytes=16-31', 16, 31], ['bytes=500-', 500, 511], ['bytes=500-999', 500, 511]]) {
    for (const method of ['GET', 'HEAD']) {
      const response = await request('/manual/media/guide.mp4', method, {Range: range});
      assert.equal(response.status, 206);
      assert.equal(response.headers['content-range'], `bytes ${start}-${end}/512`);
      assert.equal(response.headers['accept-ranges'], 'bytes');
      assert.equal(Number(response.headers['content-length']), end - start + 1);
      assert.deepEqual(response.bytes, method === 'HEAD' ? Buffer.alloc(0) : media.subarray(start, end + 1));
      checks++;
    }
  }
  for (const range of ['', 'bytes=-10', 'bytes=0-1,4-5', 'bytes=512-', 'bytes=31-16', 'bytes=9007199254740992-', 'items=0-2']) {
    for (const method of ['GET', 'HEAD']) {
      const response = await request('/manual/media/guide.mp4', method, {Range: range});
      assert.equal(response.status, 416, range);
      assert.equal(response.headers['content-range'], 'bytes */512');
      assert.equal(response.bytes.length, 0);
      checks++;
    }
  }
  const empty = await request('/manual/empty.mp4', 'GET', {Range: 'bytes=0-'});
  assert.equal(empty.status, 416);
  assert.equal(empty.headers['content-range'], 'bytes */0');
  assert.equal(empty.bytes.length, 0);
  checks++;
  const ordinaryRange = await request('/manual/guide.txt', 'GET', {Range: 'bytes=0-1'});
  assert.equal(ordinaryRange.status, 200);
  assert.deepEqual(ordinaryRange.bytes, bodies.txt);
  checks++;
  assert.equal((await request('/manual/boundary.txt', 'HEAD')).status, 200);
  checks++;
  for (const method of ['POST', 'PUT', 'DELETE']) {
    assert.equal((await request('/manual/guide.html', method)).status, 405);
    checks++;
  }
  for (const route of ['/manual/%2e%2e/private.md', '/manual/%2f../private.md', '/manual/%ZZ',
    '/manual/media%5cguide.mp4', '/manual/private.md', '/manual/tampered.html',
    '/manual/manifest.json', '/manual/oversized.txt']) await denied(route);
  await denied('/manual/tampered.html', 'HEAD');
  // Bad integrity wins over Range processing, so unverified content never leaks.
  files['media/guide.mp4'] = {...entry(media), sha256: '0'.repeat(64)};
  writeManifest();
  await denied('/manual/media/guide.mp4', 'GET', {Range: 'bytes=0-3'});
  files['media/guide.mp4'] = entry(media);
  for (const bytes of [-1, '512', null, 8 * 1024 * 1024 + 1]) {
    files['media/guide.mp4'] = {...entry(media), bytes};
    writeManifest();
    await denied('/manual/media/guide.mp4');
  }
  files['media/guide.mp4'] = entry(media);
  writeManifest();
  for (const [name, target, type] of [['linked.md', path.join(root, 'private.md'), 'file'],
    ['linked-dir', path.join(dir, 'media'), process.platform === 'win32' ? 'junction' : 'dir']]) {
    try { fs.symlinkSync(target, path.join(dir, name), type); }
    catch (error) {
      if (process.platform !== 'win32' || !['EPERM', 'EACCES'].includes(error.code)) throw error;
      skipped.push(`Windows could not create ${type} symlink fixture`);
      continue;
    }
    const resource = name === 'linked.md' ? name : `${name}/guide.mp4`;
    files[resource] = name === 'linked.md' ? entry(privateBody) : entry(media);
    writeManifest();
    await denied('/manual/' + resource);
  }
  fs.writeFileSync(manifestPath, '{invalid');
  await denied('/manual/guide.html');
  writeManifest();
  assert.equal((await request('/manual/guide.html')).status, 200);
  checks++;
  const generation = path.join(root, 'generation');
  fs.renameSync(dir, generation);
  fs.symlinkSync(generation, dir, process.platform === 'win32' ? 'junction' : 'dir');
  const currentGeneration = await request('/manual/guide.html');
  assert.equal(currentGeneration.status, 200);
  assert.deepEqual(currentGeneration.bytes, bodies.html);
  checks++;
  console.log(JSON.stringify({checks, skipped, publicManualPolicyPreserved: true,
    providerCalls: 0, deploymentChanges: 0}));
}
main().catch(error => { console.error(error); process.exitCode = 1; }).finally(async () => {
  if (child && child.exitCode === null) {
    const exited = new Promise(resolve => child.once('exit', resolve));
    child.kill();
    await exited;
  }
  assert(path.dirname(root) === os.tmpdir() && path.basename(root).startsWith('dsh-manual-'));
  fs.rmSync(root, {recursive: true, force: true});
});
