import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
const { rewritePromptAdmission } = createRequire(import.meta.url)('../scripts/prompt_admission_diagnostics.cjs');

class RemoteError extends Error { constructor(code, message, data) { super(message); this.code = code; this.data = data; } }
const upstream = q => `async function admit(op){ try { await op(); } catch (error) { if (error && error.remote) throw error; throw new RemoteError(${q}session/agent-busy${q}, ${q}prompt rejected${q}, { reason: String(error) }); } return { accepted: true }; }`;

for (const q of ['"', "'"]) {
  const { source, changed } = rewritePromptAdmission(upstream(q));
  assert.equal(changed, true);
  assert.deepEqual(rewritePromptAdmission(source), { source, changed: false }, 'Idempotent');
  const logged = [];
  const original = console.error;
  console.error = (...args) => logged.push(args.join(' '));
  try {
    const admit = new Function('RemoteError', `${source}; return admit;`)(RemoteError);
    await assert.rejects(admit(async () => { throw new TypeError('image store failed key=abc123 at /state/attachments'); }), error => {
      assert.equal(error.code, 'session/agent-busy', 'Client-visible code is unchanged');
      assert.match(error.message, /^prompt rejected: image store failed key=<redacted>/, 'The real cause is shown, secrets redacted');
      return true;
    });
    const secrets = ['Authorization: Bearer abc.def-ghi', '"api_key": "sk-live1234567890"', 'password=hunter22', 'upstream sk-proj_ABCDEFGHIJ failed'];
    await assert.rejects(admit(async () => { throw new Error(secrets.join(' | ')); }), error => {
      for (const leaked of ['abc.def-ghi', 'sk-live1234567890', 'hunter22', 'sk-proj_ABCDEFGHIJ']) assert(!error.message.includes(leaked), 'Redacted: ' + leaked);
      assert.match(error.message, /Bearer <redacted>/);
      return true;
    });
    assert.equal((await admit(async () => {})).accepted, true, 'Successful admission is unchanged');
  } finally { console.error = original; }
  assert(logged.some(line => line.startsWith('[dsh] prompt admission failed:') && line.includes('image store failed') && !line.includes('abc123')), 'The cause is logged without secrets');
  assert(!logged.some(line => /hunter22|sk-live1234567890|abc\.def-ghi/.test(line)), 'No logged line carries a secret');
}
assert.throws(() => rewritePromptAdmission('no such code'), /DRIFT/, 'Upstream drift fails the build instead of silently skipping');
console.log('Prompt admission diagnostics: real cause shown and logged with secrets redacted; code unchanged; idempotent; drift fails closed');
