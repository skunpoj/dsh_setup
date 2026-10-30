import assert from 'node:assert/strict';
import { rewritePromptAdmission } from '../scripts/configure_prompt_admission_diagnostics.mjs';

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
    assert.equal((await admit(async () => {})).accepted, true, 'Successful admission is unchanged');
  } finally { console.error = original; }
  assert(logged.some(line => line.startsWith('[dsh] prompt admission failed:') && line.includes('image store failed') && !line.includes('abc123')), 'The cause is logged without secrets');
}
assert.throws(() => rewritePromptAdmission('no such code'), /DRIFT/, 'Upstream drift fails the build instead of silently skipping');
console.log('Prompt admission diagnostics: real cause shown and logged with secrets redacted; code unchanged; idempotent; drift fails closed');
