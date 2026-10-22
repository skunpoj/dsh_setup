'use strict';
// Operator-selected compatibility for the one qualified RegChat origin/alias.
// This does not change application authentication or rewrite arbitrary HTML URLs.
const MAX_BYTES = 2 * 1024 * 1024;
const UPSTREAM = 'https://regchat.dev.apps.mlops.bot.or.th';
const ALIAS = 'https://regchat.aiportal.bot.or.th';
function refuse(message) { const e = new Error(message); e.status = 502; throw e; }
function enabled(target, publicOrigin) {
  const adapter = target.policy.frontendAdapter;
  if (adapter === undefined) return false;
  if (adapter !== 'regchat-gradio-root' || target.url.origin !== UPSTREAM ||
      target.basePath !== '' || publicOrigin !== ALIAS)
    refuse('Unqualified frontend adapter mapping');
  return true;
}
function route(path) { return new URL(path, ALIAS).pathname; }
function eligible(target, publicOrigin, method, path, status, headers) {
  if (!enabled(target, publicOrigin) || method !== 'GET' || status !== 200) return false;
  const p = route(path), type = String(headers['content-type'] || '').split(';')[0].trim().toLowerCase();
  if (p === '/' && type === 'text/html') return true;
  if (p === '/config' && type === 'application/json') return true;
  return false;
}
function jsonEnd(text, start) {
  if (text[start] !== '{') refuse('Expected Gradio configuration object');
  let depth = 0, quoted = false, escaped = false;
  for (let i = start; i < text.length; i++) {
    const c = text[i];
    if (quoted) { if (escaped) escaped = false; else if (c === '\\') escaped = true; else if (c === '"') quoted = false; }
    else if (c === '"') quoted = true;
    else if (c === '{' || c === '[') depth++;
    else if (c === '}' || c === ']') { if (--depth === 0) return i + 1; }
  }
  refuse('Incomplete Gradio configuration');
}
function rewrittenConfig(text) {
  let config;
  try { config = JSON.parse(text); } catch { refuse('Invalid Gradio configuration JSON'); }
  if (!config || Array.isArray(config) || typeof config !== 'object' || config.root !== UPSTREAM)
    refuse('Unexpected Gradio configuration root');
  config.root = ALIAS;
  // Safe inside an existing script element, including user-supplied text values.
  return JSON.stringify(config).replace(/</g, '\\u003c').replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');
}
function transform(body, headers, path, target, publicOrigin) {
  if (!enabled(target, publicOrigin) || body.length > MAX_BYTES) refuse('Invalid frontend adaptation input');
  const encoding = String(headers['content-encoding'] || 'identity').toLowerCase();
  if (encoding !== 'identity') refuse('Compressed frontend adaptation is not qualified');
  if (/sha(?:256|384|512)-/i.test(String(headers['content-security-policy'] || '') + String(headers['content-security-policy-report-only'] || '')))
    refuse('Script hash policy requires separate frontend qualification');
  let text;
  try { text = new TextDecoder('utf-8', {fatal:true}).decode(body); } catch { refuse('Invalid UTF-8 frontend response'); }
  if (route(path) === '/config') text = rewrittenConfig(text);
  else {
    const matches = [...text.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script\s*>/gi)]
      .flatMap(script => [...script[1].matchAll(/\bwindow\.gradio_config\s*=\s*/g)]
        .map(m => ({script, start:script.index + script[0].indexOf(script[1]) + m.index + m[0].length})));
    if (matches.length !== 1) refuse('Expected one inline Gradio configuration');
    const {script, start} = matches[0], end = jsonEnd(text, start);
    const scriptEnd = script.index + script[0].lastIndexOf('</');
    if (end > scriptEnd || !/^\s*(?:;|$)/.test(text.slice(end, scriptEnd))) refuse('Unexpected Gradio assignment syntax');
    text = text.slice(0, start) + rewrittenConfig(text.slice(start, end)) + text.slice(end);
  }
  const result = Buffer.from(text, 'utf8'), resultHeaders = {...headers};
  for (const k of ['content-length','content-encoding','etag','content-md5','digest','content-digest','repr-digest','accept-ranges','last-modified']) delete resultHeaders[k];
  resultHeaders['content-length'] = String(result.length);
  resultHeaders['cache-control'] = 'no-store';
  return {body:result, headers:resultHeaders};
}
module.exports = {MAX_BYTES, enabled, eligible, transform};
