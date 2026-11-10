'use strict';
// Gateway side of the engine drain snapshot: ONE plain-HTTP GET to the in-cluster exporter Service
// (k8s/dsh-engine-drain-exporter.yaml). The gateway sends no credential, holds no cluster token and
// calls no cluster API; any doubt (bad URL, timeout, non-200, too large, bad JSON) gives no snapshot,
// and the restart request then refuses (fail closed).
const http = require('node:http');
const crypto = require('node:crypto');

const MAX_BYTES = 262144;
const TIMEOUT_MS = 2000;
// Only an in-cluster Service name or loopback (tests), only http, only the one snapshot path.
const ALLOWED = /^http:\/\/(?:[a-z0-9-]+(?:\.[a-z0-9-]+)*\.svc\.cluster\.local|[a-z0-9-]+\.[a-z0-9-]+\.svc|127\.0\.0\.1)(?::(\d{2,5}))?\/engine-drain\.json$/;

function validUrl(value) {
  if (typeof value !== 'string' || !ALLOWED.test(value)) return null;
  const url = new URL(value);
  return url.username || url.password || url.search || url.hash ? null : url;
}

// Resolves to {snapshot, sha256, error}; never rejects.
function fetchSnapshot(value, {timeoutMs = TIMEOUT_MS} = {}) {
  const url = validUrl(value);
  if (!url) return Promise.resolve({snapshot: null, sha256: null, error: 'invalid-url'});
  return new Promise(resolve => {
    let settled = false;
    const done = result => { if (!settled) { settled = true; resolve(result); } };
    const req = http.request({host: url.hostname, port: url.port || 80, path: url.pathname, method: 'GET',
      headers: {Accept: 'application/json'}, timeout: timeoutMs}, res => {
      if (res.statusCode !== 200) { res.resume(); return done({snapshot: null, sha256: null, error: 'status-' + res.statusCode}); }
      const chunks = []; let size = 0;
      res.on('data', chunk => { size += chunk.length; if (size > MAX_BYTES) { req.destroy(); done({snapshot: null, sha256: null, error: 'too-large'}); } else chunks.push(chunk); });
      res.on('end', () => {
        const raw = Buffer.concat(chunks);
        try { done({snapshot: JSON.parse(raw.toString('utf8')), sha256: crypto.createHash('sha256').update(raw).digest('hex'), error: null}); }
        catch { done({snapshot: null, sha256: null, error: 'bad-json'}); }
      });
      res.on('error', () => done({snapshot: null, sha256: null, error: 'read-error'}));
    });
    req.on('timeout', () => { req.destroy(); done({snapshot: null, sha256: null, error: 'timeout'}); });
    req.on('error', () => done({snapshot: null, sha256: null, error: 'unreachable'}));
    req.end();
  });
}

module.exports = {fetchSnapshot, validUrl, MAX_BYTES, TIMEOUT_MS};
