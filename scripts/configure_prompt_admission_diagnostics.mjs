import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { pathToFileURL } from 'node:url';

// Upstream reports EVERY unexpected prompt-admission failure (for example an
// image that cannot be stored or a model lookup error) as
// "prompt rejected (session/agent-busy)" and logs nothing, so the real cause
// is invisible. Keep the same error code for client compatibility, but put a
// short redacted cause in the message and log the stack to the container log.
const QUOTES = [['"', '"'], ["'", "'"]];
const original = q => `throw new RemoteError(${q}session/agent-busy${q}, ${q}prompt rejected${q}, { reason: String(error) });`;
const replacement = q => `{ const dshDetail = String(error && error.message || error).replace(/(token|key|secret|password)=\\S+/gi, ${q}$1=<redacted>${q}).slice(0, 240); console.error(${q}[dsh] prompt admission failed: ${q} + (error && error.stack ? String(error.stack).replace(/(token|key|secret|password)=\\S+/gi, ${q}$1=<redacted>${q}).slice(0, 2000) : dshDetail)); throw new RemoteError(${q}session/agent-busy${q}, ${q}prompt rejected: ${q} + dshDetail, { reason: String(error) }); }`;

export function rewritePromptAdmission(source) {
  let changed = false, patched = 0;
  for (const [q] of QUOTES) {
    const before = source.split(original(q)).length - 1;
    const after = source.split(replacement(q)).length - 1;
    if (before === 0 && after === 0) continue;
    if (before > 1 || after > 1 || (before === 1 && after === 1)) throw new Error('PROMPT_ADMISSION_SOURCE_DRIFT');
    if (before === 1) { source = source.replace(original(q), replacement(q)); changed = true; }
    patched += 1;
  }
  if (patched !== 1) throw new Error('PROMPT_ADMISSION_SOURCE_DRIFT');
  return { source, changed };
}

export async function configurePromptAdmissionDiagnostics(packageRoot) {
  const base = path.join(path.resolve(packageRoot), 'node_modules/@deepseek-ai/dsh-api-session-controller/lib');
  const results = [];
  for (const rel of ['index.js', 'types/commands.js']) {
    const file = path.join(base, rel);
    const before = await fs.readFile(file, 'utf8');
    if (Buffer.byteLength(before) > 4194304) throw new Error('PROMPT_ADMISSION_FILE_BOUND');
    const result = rewritePromptAdmission(before);
    if (result.changed) {
      if (await fs.readFile(file, 'utf8') !== before) throw new Error('PROMPT_ADMISSION_CONCURRENT_CHANGE');
      await fs.writeFile(file, result.source);
    }
    if (await fs.readFile(file, 'utf8') !== result.source) throw new Error('PROMPT_ADMISSION_READBACK');
    const digest = v => crypto.createHash('sha256').update(v).digest('hex');
    results.push({ file: rel, changed: result.changed, beforeSHA256: digest(before), afterSHA256: digest(result.source) });
  }
  return { scope: 'BUILD_TIME_PROMPT_ADMISSION_DIAGNOSTICS', errorCodeUnchanged: 'session/agent-busy', results };
}

if (typeof process !== 'undefined' && process.argv[1] &&
    import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  configurePromptAdmissionDiagnostics(process.argv[2] || '/usr/local/lib/node_modules/@deepseek-ai/dsh')
    .then(result => console.log(JSON.stringify(result)))
    .catch(error => { console.error(error.message); process.exitCode = 1; });
}
