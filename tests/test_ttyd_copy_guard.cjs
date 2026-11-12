'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { injectCopyGuard, shouldGuard, GUARD } = require('../scripts/ttyd_copy_guard.js');

const page = '<!DOCTYPE html><html><head><meta charset="UTF-8"><title>ttyd</title></head><body><script>/* ttyd bundle */</script></body></html>';
const guarded = injectCopyGuard(page);
assert(guarded.includes(GUARD));
assert(guarded.indexOf(GUARD) < guarded.indexOf('/* ttyd bundle */'), 'the guard runs before ttyd\'s own script');
assert.equal(injectCopyGuard(guarded), guarded, 'idempotent');
assert(injectCopyGuard('<body>x</body>').startsWith(GUARD), 'no <head>: guard goes first');
assert.equal(injectCopyGuard(null), null);

// The injected script really blocks only the 'copy' command.
const calls = [];
const sandbox = { document: { execCommand: (command) => { calls.push(command); return true; } } };
vm.runInNewContext(GUARD.replace(/^<script>|<\/script>$/g, ''), sandbox);
assert.equal(sandbox.document.execCommand('copy'), false);
assert.equal(sandbox.document.execCommand('COPY'), false);
assert.equal(sandbox.document.execCommand('paste'), true);
assert.deepEqual(calls, ['paste']);

// Only ttyd's HTML, only GET 200, and the operator can keep upstream behaviour.
const base = { port: 7681, method: 'GET', statusCode: 200, contentType: 'text/html', env: {} };
assert.equal(shouldGuard(base), true);
assert.equal(shouldGuard({ ...base, port: 8888 }), false);
assert.equal(shouldGuard({ ...base, method: 'POST' }), false);
assert.equal(shouldGuard({ ...base, statusCode: 304 }), false);
assert.equal(shouldGuard({ ...base, contentType: 'application/javascript' }), false);
assert.equal(shouldGuard({ ...base, env: { DSH_TTYD_COPY_ON_SELECT: '1' } }), false);

// The gateway uses it for the terminal port and forces an uncompressed upstream response so the HTML can be edited.
const gateway = fs.readFileSync(path.join(__dirname, '..', 'scripts', 'auth_proxy.js'), 'utf8');
assert(gateway.includes("require('./ttyd_copy_guard.js')"));
assert(/shouldGuard\(\{ port: targetPort/.test(gateway));
console.log('ttyd copy guard: ok');
