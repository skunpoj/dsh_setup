'use strict';
// Candidate library only. Existing DSH owner/session checks must call resolveTarget.
// Public HTTPS requires global policy; private origins require explicit pinned policy.
// Never forwards DSH credentials to an application.
const https = require('node:https');
const dns = require('node:dns').promises;
const net = require('node:net');
const gradioAlias = require('./gradio_alias');

function reject(message, status = 400) {
  const error = new Error(message); error.status = status; throw error;
}
function originURL(value) {
  let u;
  try { u = new URL(value); } catch { reject('Invalid upstream URL'); }
  if (u.protocol !== 'https:' || u.username || u.password || u.hash || u.search || net.isIP(u.hostname) || u.hostname.startsWith('[') || u.hostname.endsWith('.'))
    reject('Upstream must be a named HTTPS origin without credentials, query or fragment');
  if (!/^\/[\w\-./~%]*$/.test(u.pathname) || /%2e|%2f|%5c/i.test(u.pathname)) reject('Unsupported upstream base path');
  return u;
}
function forbiddenAddress(address) {
  // IPv6 support must be separately qualified; deny rather than silently route it.
  if (net.isIP(address) !== 4) return true;
  const [a,b] = address.split('.').map(Number);
  return a === 0 || a === 127 || a === 169 && b === 254 || a >= 224;
}
const PRIVATE4 = new net.BlockList();
for (const [address,bits] of [['0.0.0.0',8],['10.0.0.0',8],['100.64.0.0',10],['127.0.0.0',8],['169.254.0.0',16],['172.16.0.0',12],['192.0.0.0',24],['192.0.2.0',24],['192.88.99.0',24],['192.168.0.0',16],['198.18.0.0',15],['198.51.100.0',24],['203.0.113.0',24],['224.0.0.0',3]]) PRIVATE4.addSubnet(address,bits,'ipv4');
const GLOBAL6 = new net.BlockList(); GLOBAL6.addSubnet('2000::',3,'ipv6');
const SPECIAL6 = new net.BlockList();
for (const [address,bits] of [['2001::',23],['2001:db8::',32],['2002::',16],['3fff::',20]]) SPECIAL6.addSubnet(address,bits,'ipv6');
function publicAddress(address) {
  const family=net.isIP(address);
  if(family===4)return !PRIVATE4.check(address,'ipv4');
  if(family===6)return GLOBAL6.check(address,'ipv6')&&!SPECIAL6.check(address,'ipv6');
  return false;
}
function resolveTarget(entry, user, mode, policies) {
  if (!user || entry?.owner !== user || entry.enabled === false) reject('Application is not owned by this account', 404);
  const mapping = entry.targets?.[mode];
  if (mapping?.type !== 'external') reject('No external mapping in this environment', 404);
  const url = originURL(mapping.url);
  let policy = Object.hasOwn(policies || {},url.origin) ? policies[url.origin] : null;
  if(policy) {
    if(!Array.isArray(policy.addresses)||!policy.addresses.length||policy.addresses.some(forbiddenAddress))reject('Invalid pinned upstream policy',403);
  } else {
    const ports=policies?.publicPorts || [443];
    if(mode!=='on'||policies?.publicHttps!==true||!Array.isArray(ports)||!ports.includes(Number(url.port||443)))reject('Public HTTPS forwarding is disabled or port is not allowed',403);
    if(!url.hostname.includes('.')||/\.(localhost|local|internal|invalid|test|example|svc|cluster\.local)$/i.test(url.hostname))reject('Public target requires a public DNS name',403);
    policy={publicOnly:true};
  }
  return {url, policy, basePath: url.pathname.replace(/\/$/, '')};
}
async function connectionOptions(target, lookup = dns.lookup) {
  const addresses = await lookup(target.url.hostname, {all: true, verbatim: true});
  if (!addresses.length || addresses.some(a => a.family !== net.isIP(a.address) || (target.policy.publicOnly ? !publicAddress(a.address) : forbiddenAddress(a.address) || !target.policy.addresses.includes(a.address))))
    reject('Upstream DNS is outside the approved address set', 502);
  const selected = addresses[0];
  return {hostname: target.url.hostname, port: target.url.port || 443,
    servername: target.url.hostname, rejectUnauthorized: true,
    ...(target.policy.ca ? {ca: target.policy.ca} : {}),
    lookup: (_hostname, options, callback) => options?.all
      ? callback(null, [selected]) : callback(null, selected.address, selected.family)};
}
const HOP = new Set(['connection','keep-alive','proxy-connection','proxy-authenticate','proxy-authorization','te','trailer','transfer-encoding','upgrade']);
function protectedCookie(name, protectedCookies) {
  return protectedCookies.includes(name) || ['dsh_auth','dsh2_auth','dsh3_auth'].includes(name) || name.startsWith('dsh-auth-');
}
function cleanHeaders(headers, protectedCookies) {
  const blocked = new Set([...HOP, ...(headers.connection || '').toLowerCase().split(',').map(x=>x.trim()),
    'authorization','forwarded','x-forwarded-host','x-forwarded-proto','x-forwarded-for']);
  const result = {};
  for (const [raw,value] of Object.entries(headers)) {
    const key = raw.toLowerCase();
    if (blocked.has(key) || key.startsWith('x-dsh-')) continue;
    if (key === 'cookie') {
      const cookies = String(value).split(';').map(x=>x.trim()).filter(x=>x && !protectedCookie(x.split('=')[0], protectedCookies));
      if (cookies.length) result.cookie = cookies.join('; ');
    } else result[key] = value;
  }
  return result;
}
function requestPath(path, target) {
  if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//') || /[\r\n\\]/.test(path) || /%2e|%2f|%5c/i.test(path.split('?')[0])) reject('Invalid request path');
  const normalized = new URL(path, 'https://public.invalid');
  return target.basePath + normalized.pathname + normalized.search;
}
function outgoingHeaders(req, target, publicOrigin, protectedCookies, websocket = false) {
  const pub = new URL(publicOrigin);
  if (pub.protocol !== 'https:' || pub.origin !== publicOrigin) reject('Invalid trusted public origin');
  const headers = cleanHeaders(req.headers, protectedCookies);
  headers.host = target.url.host;
  headers['x-forwarded-host'] = pub.host;
  headers['x-forwarded-proto'] = 'https';
  if (headers.origin) {
    if (headers.origin !== pub.origin) reject('Cross-origin application request refused', 403);
    headers.origin = target.url.origin;
  }
  if (headers.referer) {
    let ref;
    try { ref = new URL(headers.referer); } catch { reject('Invalid referrer'); }
    if (ref.origin !== pub.origin) delete headers.referer;
    else headers.referer = target.url.origin + requestPath(ref.pathname + ref.search, target);
  }
  if (websocket) { headers.connection = 'Upgrade'; headers.upgrade = 'websocket'; }
  return headers;
}
function responseHeaders(input, target, publicOrigin, protectedCookies) {
  const result = cleanHeaders(input, protectedCookies);
  if (input.location) {
    const location = new URL(input.location, target.url);
    if (location.protocol !== 'https:') reject('Unsafe upstream redirect', 502);
    if (location.origin === target.url.origin) {
      if (target.basePath && location.pathname !== target.basePath && !location.pathname.startsWith(target.basePath + '/'))
        reject('Upstream redirect escapes mapped base path', 502);
      result.location = publicOrigin + (location.pathname.slice(target.basePath.length) || '/') + location.search + location.hash;
    } else result.location = location.href; // Browser SSO may legitimately leave the alias.
  }
  if (input['set-cookie']) {
    const kept = [];
    for (const cookie of [].concat(input['set-cookie'])) {
      const name = cookie.split('=',1)[0];
      if (protectedCookie(name, protectedCookies)) continue;
      const domain = /;\s*domain=([^;]+)/i.exec(cookie);
      if (domain && domain[1].replace(/^\./,'').toLowerCase() !== target.url.hostname) continue;
      let value = cookie.replace(/;\s*domain=[^;]+/ig,'');
      value = value.replace(/;\s*path=([^;]*)/i, (_m,p) => {
        if (target.basePath && p !== target.basePath && !p.startsWith(target.basePath + '/') && p !== '/') reject('Upstream cookie escapes mapped path',502);
        return '; Path=' + (p === '/' ? '/' : p.slice(target.basePath.length) || '/');
      });
      if (!/;\s*secure(?:;|$)/i.test(value)) value += '; Secure';
      kept.push(value);
    }
    if (kept.length) result['set-cookie'] = kept; else delete result['set-cookie'];
  }
  return result;
}
async function proxyHTTP(req, res, options) {
  const {target, publicOrigin, protectedCookies, lookup} = options;
  const connection = await connectionOptions(target, lookup);
  if(options.authorize&&!options.authorize())reject('Application access changed',403);
  const path = requestPath(req.url, target);
  const headers = outgoingHeaders(req, target, publicOrigin, protectedCookies);
  const adaptFrontend = gradioAlias.enabled(target, publicOrigin);
  if (adaptFrontend) {
    headers['accept-encoding'] = 'identity';
    if (req.method === 'GET' && ['/', '/config'].includes(new URL(req.url, publicOrigin).pathname)) {
      // A cached upstream body may contain the original origin. Always qualify
      // a complete fresh configuration rather than forwarding 304/206 results.
      for (const key of ['if-none-match','if-modified-since','if-range','range']) delete headers[key];
    }
  }
  const upstream = https.request({...connection, path, method: req.method, headers}, response => {
    try {
      if (gradioAlias.eligible(target, publicOrigin, req.method, req.url, response.statusCode, response.headers)) {
        const chunks = []; let bytes = 0, failed = false;
        const fail = () => { if (failed) return; failed = true; response.destroy(); if (!res.headersSent) {res.writeHead(502);res.end('Unqualified application frontend response');} else res.destroy(); };
        response.on('error', fail);
        response.on('data', chunk => { bytes += chunk.length; if (bytes > gradioAlias.MAX_BYTES) fail(); else chunks.push(chunk); });
        response.on('end', () => {
          if (failed) return;
          try {
            const adapted = gradioAlias.transform(Buffer.concat(chunks), response.headers, req.url, target, publicOrigin);
            res.writeHead(response.statusCode, responseHeaders(adapted.headers, target, publicOrigin, protectedCookies));
            res.end(adapted.body);
          } catch { fail(); }
        });
        return;
      }
      res.writeHead(response.statusCode, responseHeaders(response.headers, target, publicOrigin, protectedCookies));
      response.on('error', () => res.destroy());
      response.pipe(res);
    } catch (e) { response.destroy(); if (!res.headersSent) {res.writeHead(e.status || 502);res.end('Invalid upstream response');}else res.destroy(); }
  });
  upstream.setTimeout(60_000, () => upstream.destroy(new Error('Upstream timeout')));
  upstream.on('error', () => { if (!res.headersSent) {res.writeHead(502);res.end('Upstream connection failed');} else res.destroy(); });
  req.on('aborted', () => upstream.destroy());
  req.on('error', () => upstream.destroy());
  res.on('close', () => upstream.destroy());
  req.pipe(upstream); // No automatic retries of POSTs or other requests.
}
async function proxyWebSocket(req, socket, head, options) {
  const {target, publicOrigin, protectedCookies, lookup} = options;
  const connection = await connectionOptions(target, lookup);
  if(options.authorize&&!options.authorize())reject('Application access changed',403);
  const upstream = https.request({...connection, path: requestPath(req.url,target), method: 'GET',
    headers: outgoingHeaders(req,target,publicOrigin,protectedCookies,true)});
  upstream.setTimeout(60_000, () => upstream.destroy(new Error('Upstream timeout')));
  upstream.on('upgrade', (response, remote, remoteHead) => {
    try {
      const headers = responseHeaders(response.headers,target,publicOrigin,protectedCookies);
      headers.connection='Upgrade'; headers.upgrade='websocket';
      socket.write('HTTP/1.1 101 Switching Protocols\r\n' + Object.entries(headers).flatMap(([k,v])=>[].concat(v).map(x=>k+': '+x)).join('\r\n')+'\r\n\r\n');
      if (remoteHead.length) socket.write(remoteHead);
      if (head.length) remote.write(head);
      remote.on('error',()=>socket.destroy()); socket.on('error',()=>remote.destroy());
      remote.on('close',()=>socket.destroy()); socket.on('close',()=>remote.destroy());
      remote.pipe(socket); socket.pipe(remote);
    } catch {remote.destroy();socket.destroy();}
  });
  upstream.on('response', response=>{socket.end('HTTP/1.1 '+response.statusCode+' Upstream refused\r\nConnection: close\r\n\r\n');response.destroy();});
  upstream.on('error',()=>socket.destroy()); socket.on('error',()=>upstream.destroy());
  socket.on('close',()=>upstream.destroy()); upstream.end();
}
module.exports={originURL,forbiddenAddress,publicAddress,resolveTarget,connectionOptions,cleanHeaders,requestPath,outgoingHeaders,responseHeaders,proxyHTTP,proxyWebSocket};
