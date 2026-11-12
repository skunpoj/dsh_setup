'use strict';
// Operator-selected Gradio compatibility; deployment defaults and explicit origins are distinct.
// This does not change application authentication or rewrite arbitrary HTML URLs.
const MAX_BYTES = 2 * 1024 * 1024;
function originSetting(value) {
  if (!value) return '';
  let parsed;
  try { parsed = new URL(value); } catch { throw Error('Invalid Gradio origin setting'); }
  if (parsed.protocol !== 'https:' || parsed.username || parsed.password || parsed.pathname !== '/' ||
      parsed.search || parsed.hash || !parsed.hostname.includes('.') ||
      require('node:net').isIP(parsed.hostname) || parsed.hostname.startsWith('[') || parsed.hostname.endsWith('.'))
    throw Error('Gradio settings require named HTTPS origins without credentials, paths or queries');
  return parsed.origin;
}
const configuredUpstream = originSetting(process.env.DSH_GRADIO_UPSTREAM_ORIGIN);
const configuredAlias = originSetting(process.env.DSH_GRADIO_PUBLIC_ORIGIN);
if (Boolean(configuredUpstream) !== Boolean(configuredAlias)) throw Error('Both Gradio origins must be configured');
const configured = Boolean(configuredUpstream);
// Operator-owned defaults preserve the private deployment; public profiles can disable them.
function deploymentDefaults(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      Object.keys(value).sort().join(',') !== 'aliases,upstream' ||
      typeof value.upstream !== 'string' || !Array.isArray(value.aliases) ||
      value.aliases.some(alias => typeof alias !== 'string' || !alias))
    throw Error('Invalid Gradio deployment defaults');
  const upstream = originSetting(value.upstream), aliases = value.aliases.map(originSetting);
  if (Boolean(upstream) !== Boolean(aliases.length) || new Set(aliases).size !== aliases.length)
    throw Error('Gradio deployment defaults require a paired upstream and unique aliases');
  return {upstream, aliases};
}
// The gateway runs from a FLAT source ConfigMap (rollout_dsh_sources.py), so the defaults file is a sibling there;
// the repository layout keeps it in ../config. Only a missing file falls through; a broken one still throws.
function loadDeploymentDefaults() {
  try { return require('./gradio-alias-defaults.json'); }
  catch (error) { if (error.code !== 'MODULE_NOT_FOUND') throw error; }
  return require('../config/gradio-alias-defaults.json'); // cm-optional: repository layout only
}
const defaults = configured ? {upstream:'', aliases:[]} : deploymentDefaults(loadDeploymentDefaults());
const UPSTREAM = configuredUpstream || defaults.upstream;
const ALIAS = configuredAlias || defaults.aliases[0] || '';
const ALIASES = new Set(configured ? [ALIAS] : defaults.aliases);
function refuse(message) { const e = new Error(message); e.status = 502; throw e; }
function enabled(target, publicOrigin) {
  const adapter = target.policy.frontendAdapter;
  if (adapter === undefined) return false;
  if (adapter !== (configured ? 'gradio-root' : 'regchat-gradio-root') || !UPSTREAM || !ALIAS || target.url.origin !== UPSTREAM ||
      target.basePath !== '' || !ALIASES.has(publicOrigin))
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
function rewrittenConfig(text, publicOrigin) {
  let config;
  try { config = JSON.parse(text); } catch { refuse('Invalid Gradio configuration JSON'); }
  if (!config || Array.isArray(config) || typeof config !== 'object' || config.root !== UPSTREAM)
    refuse('Unexpected Gradio configuration root');
  config.root = publicOrigin;
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
  if (route(path) === '/config') text = rewrittenConfig(text, publicOrigin);
  else {
    const matches = [...text.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script\s*>/gi)]
      .flatMap(script => [...script[1].matchAll(/\bwindow\.gradio_config\s*=\s*/g)]
        .map(m => ({script, start:script.index + script[0].indexOf(script[1]) + m.index + m[0].length})));
    if (matches.length !== 1) refuse('Expected one inline Gradio configuration');
    const {script, start} = matches[0], end = jsonEnd(text, start);
    const scriptEnd = script.index + script[0].lastIndexOf('</');
    if (end > scriptEnd || !/^\s*(?:;|$)/.test(text.slice(end, scriptEnd))) refuse('Unexpected Gradio assignment syntax');
    text = text.slice(0, start) + rewrittenConfig(text.slice(start, end), publicOrigin) + text.slice(end);
  }
  const result = Buffer.from(text, 'utf8'), resultHeaders = {...headers};
  for (const k of ['content-length','content-encoding','etag','content-md5','digest','content-digest','repr-digest','accept-ranges','last-modified']) delete resultHeaders[k];
  resultHeaders['content-length'] = String(result.length);
  resultHeaders['cache-control'] = 'no-store';
  return {body:result, headers:resultHeaders};
}
module.exports = {MAX_BYTES, enabled, eligible, transform};
