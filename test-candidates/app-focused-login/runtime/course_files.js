'use strict';

// Called only after the gateway has checked its existing session/account policy.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { pipeline } = require('stream');
const MAX_FILE = 128 * 1024 * 1024;
const MAX_MANIFEST = 1024 * 1024;
const TYPES = Object.freeze({ '.html': 'text/html; charset=utf-8', '.css': 'text/css',
  '.js': 'text/javascript', '.json': 'application/json', '.mp4': 'video/mp4',
  '.vtt': 'text/vtt; charset=utf-8', '.zip': 'application/zip', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp',
  '.woff2': 'font/woff2', '.txt': 'text/plain; charset=utf-8', '.md': 'text/plain; charset=utf-8' });
const CSP = "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; media-src 'self' blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'";
const HEADERS = { 'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'same-origin', 'Content-Security-Policy': CSP };

function parts(name) {
  if (typeof name !== 'string' || name === '.course-manifest.json' || name.length > 512 || /[\\:\x00-\x1f\x7f]/.test(name)) throw Error('Invalid course path');
  const result = name.split('/');
  if (result.some(p => !p || p === '.' || p === '..') || !Object.hasOwn(TYPES, path.posix.extname(name).toLowerCase())) throw Error('Invalid course path');
  return result;
}
function identity(s) { return [s.dev, s.ino, s.size, s.mtimeNs, s.ctimeNs].join(':'); }
function owned(s, directory) {
  if (!(directory ? s.isDirectory() : s.isFile()) || s.uid !== 0n || (s.mode & 0o222n) || (!directory && s.nlink !== 1n)) throw Error('Course must be root-owned and read-only');
}
function openMember(root, names) {
  if (process.platform !== 'linux' || !path.isAbsolute(root) || !fs.constants.O_NOFOLLOW || !fs.constants.O_DIRECTORY) throw Error('Linux descriptor serving required');
  let dir = fs.openSync('/', fs.constants.O_RDONLY | fs.constants.O_DIRECTORY);
  try {
    const dirs = root.split('/').slice(1).filter(Boolean);
    if (dirs.some(p => p === '.' || p === '..')) throw Error('Invalid root');
    for (const name of dirs) {
      const next = fs.openSync(`/proc/self/fd/${dir}/${name}`, fs.constants.O_RDONLY | fs.constants.O_DIRECTORY | fs.constants.O_NOFOLLOW);
      fs.closeSync(dir); dir = next;
    }
    owned(fs.fstatSync(dir, { bigint: true }), true);
    for (const name of names.slice(0, -1)) {
      const next = fs.openSync(`/proc/self/fd/${dir}/${name}`, fs.constants.O_RDONLY | fs.constants.O_DIRECTORY | fs.constants.O_NOFOLLOW);
      try { owned(fs.fstatSync(next, { bigint: true }), true); } catch (e) { fs.closeSync(next); throw e; }
      fs.closeSync(dir); dir = next;
    }
    const fd = fs.openSync(`/proc/self/fd/${dir}/${names.at(-1)}`, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
    try { owned(fs.fstatSync(fd, { bigint: true }), false); } catch (e) { fs.closeSync(fd); throw e; }
    return fd;
  } finally { fs.closeSync(dir); }
}
function readManifest(config) {
  if (!/^[a-f0-9]{64}$/.test(config.sha256 || '')) throw Error('Approved manifest hash required');
  const fd = openMember(config.root, ['.course-manifest.json']);
  let raw;
  try {
    const before = fs.fstatSync(fd, { bigint: true });
    if (before.size > BigInt(MAX_MANIFEST)) throw Error('Manifest too large');
    raw = Buffer.alloc(Number(before.size));
    if (fs.readSync(fd, raw, 0, raw.length, 0) !== raw.length || identity(before) !== identity(fs.fstatSync(fd, { bigint: true }))) throw Error('Manifest changed');
  } finally { fs.closeSync(fd); }
  if (crypto.createHash('sha256').update(raw).digest('hex') !== config.sha256) throw Error('Manifest hash differs');
  const manifest = JSON.parse(raw);
  if (manifest.schema !== 1 || !manifest.files || typeof manifest.files !== 'object' || Array.isArray(manifest.files)) throw Error('Invalid manifest');
  const names = Object.keys(manifest.files);
  if (!names.length || names.length > 2000 || !Object.hasOwn(manifest.files, 'index.html')) throw Error('Invalid inventory');
  for (const name of names) {
    parts(name); const item = manifest.files[name];
    if (!item || !/^[a-f0-9]{64}$/.test(item.sha256 || '') || !Number.isSafeInteger(item.bytes) || item.bytes < 0 || item.bytes > MAX_FILE) throw Error('Invalid asset');
  }
  if (Object.values(manifest.files).reduce((sum, item) => sum + item.bytes, 0) > 2 * 1024 ** 3) throw Error('Course inventory exceeds ceiling');
  return manifest.files;
}
function range(value, size) {
  if (!value) return { start: 0, end: size - 1, partial: false };
  const match = /^bytes=(\d*)-(\d*)$/.exec(value);
  if (!match || (!match[1] && !match[2]) || size === 0) throw Error('range');
  if (match.slice(1).some(n => n && !Number.isSafeInteger(Number(n)))) throw Error('range');
  let start = match[1] ? Number(match[1]) : Math.max(0, size - Number(match[2]));
  let end = match[1] && match[2] ? Math.min(Number(match[2]), size - 1) : size - 1;
  if (![start, end].every(Number.isSafeInteger) || (!match[1] && Number(match[2]) <= 0) || start < 0 || start >= size || end < start) throw Error('range');
  return { start, end, partial: true };
}
function approvedHost(value) {
  return typeof value === 'string' && /^[a-z0-9.-]+(?::\d+)?$/i.test(value) ? value.toLowerCase().replace(/:\d+$/, '') : '';
}
function routeFor(pathname, host, env = process.env) {
  const gpu = pathname === '/gpu-course' || pathname.startsWith('/gpu-course/');
  const dsh = pathname === '/manual/course' || pathname.startsWith('/manual/course/');
  if (!gpu && !dsh) return null;
  const prefix = gpu ? '/gpu-course' : '/manual/course';
  return { root: env[gpu ? 'GPU_COURSE_ROOT' : 'DSH_COURSE_ROOT'],
    sha256: env[gpu ? 'GPU_COURSE_MANIFEST_SHA256' : 'DSH_COURSE_MANIFEST_SHA256'],
    hostAllowed: Boolean(approvedHost(host) && approvedHost(host) === approvedHost(env[gpu ? 'GPU_COURSE_HOST' : 'DSH_TRUSTED_HOST'])),
    name: pathname.slice(prefix.length), canonical: '/manual/course/' };
}
function createCourseServer() {
  const cache = new Map(); // At most 128 verified identities, never file bodies.
  const inFlight = new Map(); // Bound concurrent first-read hashing across courses.
  async function verify(fd, item, key) {
    if (cache.get(key) > Date.now()) return;
    if (inFlight.size >= 4 && !inFlight.has(key)) throw Error('Verification busy');
    if (inFlight.has(key)) { await inFlight.get(key); return; }
    const operation = (async () => {
      const buffer = Buffer.alloc(1024 * 1024), digest = crypto.createHash('sha256');
      let total = 0;
      while (total < item.bytes) {
        const bytes = await new Promise((resolve, reject) => fs.read(fd, buffer, 0, Math.min(buffer.length, item.bytes - total), total, (err, n) => err ? reject(err) : resolve(n)));
        if (!bytes) throw Error('Truncated file');
        digest.update(buffer.subarray(0, bytes)); total += bytes;
      }
      if (digest.digest('hex') !== item.sha256) throw Error('Hash differs');
      if (cache.size >= 128) cache.delete(cache.keys().next().value);
      cache.set(key, Date.now() + 60000);
    })();
    inFlight.set(key, operation);
    try { await operation; } finally { inFlight.delete(key); }
  }
  return async function serveCourse(req, res, config) {
    let fd;
    try {
      if (!config.hostAllowed || !config.root) throw Error('Host or bundle not approved');
      if (!['GET', 'HEAD'].includes(req.method)) { res.writeHead(405, { ...HEADERS, Allow: 'GET, HEAD' }); return res.end(); }
      if (!config.name) { res.writeHead(307, { ...HEADERS, Location: config.canonical }); return res.end(); }
      const name = decodeURIComponent(config.name.slice(1)) || 'index.html';
      const segments = parts(name), files = readManifest(config);
      if (!Object.hasOwn(files, name)) throw Error('Not approved');
      const item = files[name]; fd = openMember(config.root, segments);
      const before = fs.fstatSync(fd, { bigint: true });
      if (before.size !== BigInt(item.bytes)) throw Error('Size differs');
      await verify(fd, item, `${config.sha256}:${item.sha256}:${identity(before)}`);
      if (identity(before) !== identity(fs.fstatSync(fd, { bigint: true }))) throw Error('File changed');
      const etag = `"${item.sha256}"`;
      let selected;
      try { selected = range(req.headers['if-range'] && req.headers['if-range'] !== etag ? undefined : req.headers.range, item.bytes); }
      catch { res.writeHead(416, { ...HEADERS, 'Content-Range': `bytes */${item.bytes}` }); return res.end(); }
      const headers = { ...HEADERS, 'Content-Type': TYPES[path.posix.extname(name).toLowerCase()],
        'Accept-Ranges': 'bytes', ETag: etag, 'Content-Length': selected.partial ? selected.end - selected.start + 1 : item.bytes };
      if (name.toLowerCase().endsWith('.zip')) headers['Content-Disposition'] = "attachment; filename*=UTF-8''" + encodeURIComponent(path.posix.basename(name));
      if (selected.partial) headers['Content-Range'] = `bytes ${selected.start}-${selected.end}/${item.bytes}`;
      res.writeHead(selected.partial ? 206 : 200, headers);
      if (req.method === 'HEAD' || item.bytes === 0) return res.end();
      const stream = fs.createReadStream(null, { fd, autoClose: true, start: selected.start, end: selected.end });
      fd = undefined;
      res.once('close', () => stream.destroy());
      pipeline(stream, res, () => {});
    } catch {
      if (!res.headersSent) { res.writeHead(404, HEADERS); res.end('Course unavailable.'); }
      else res.destroy();
    } finally { if (fd !== undefined) fs.closeSync(fd); }
  };
}
module.exports = { createCourseServer, routeFor, readManifest, openMember, parts, range, MAX_FILE, MAX_MANIFEST };
