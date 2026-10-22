'use strict';
// Directory settings and the binder password are mounted only into the gateway.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const CLIENT_SHA256 = 'addd5d000792577dff58be59a3314e8efe570689989df6c3f085c8d28efd3f1c';
class DirectoryError extends Error {
  constructor(code, status, message) { super(message); Object.assign(this, {code, status}); }
}
const denied = () => new DirectoryError('INVALID_CREDENTIALS', 401, 'The AD username or password is incorrect, or the account is unavailable.');
const unavailable = () => new DirectoryError('LDAP_UNAVAILABLE', 503, 'AD sign-in is temporarily unavailable. Retry later or contact the administrator.');
function filterValue(value) {
  return String(value).replace(/[\0()*\\]/g, c => '\\'+c.charCodeAt(0).toString(16).padStart(2, '0'));
}
function normalizeUsername(value, domain) {
  if (typeof value !== 'string' || value.length > 256) throw denied();
  let name = value.trim();
  if (name.includes('\\')) {
    const parts = name.split('\\');
    if (parts.length !== 2 || parts[0].toLowerCase() !== domain.split('.')[0].toLowerCase()) throw denied();
    name = parts[1];
  } else if (name.includes('@')) {
    const parts = name.split('@');
    if (parts.length !== 2 || parts[1].toLowerCase() !== domain.toLowerCase()) throw denied();
    name = parts[0];
  }
  name = name.toLowerCase();
  if (!/^[a-z0-9_.-]{3,30}$/.test(name) || ['__proto__','prototype','constructor'].includes(name)) throw denied();
  return name;
}
function readConfig(file) {
  const raw = fs.readFileSync(file);
  if (raw.length > 65536) throw Error('LDAP configuration exceeds limit');
  const config = JSON.parse(raw);
  if (config.version !== 1 || !Array.isArray(config.urls) || !config.urls.length || config.urls.length > 4 ||
      typeof config.domain !== 'string' || !/^(?:[a-z0-9-]+\.)+[a-z]{2,}$/i.test(config.domain) ||
      typeof config.bindDN !== 'string' || !config.bindDN || config.bindDN.length > 1024 ||
      !Array.isArray(config.searchBases) || !config.searchBases.length || config.searchBases.length > 4 ||
      config.searchBases.some(x => typeof x !== 'string' || !x || x.length > 2048) ||
      !Number.isInteger(config.timeoutMs) || config.timeoutMs < 1000 || config.timeoutMs > 10000 ||
      typeof config.bindPasswordFile !== 'string' || !path.isAbsolute(config.bindPasswordFile) ||
      typeof config.caFile !== 'string' || !path.isAbsolute(config.caFile) ||
      !['(sAMAccountName=%s)','(&(objectCategory=person)(objectClass=user)(sAMAccountName=%s))'].includes(config.searchFilter)) throw Error('Invalid LDAP configuration');
  for (const item of config.urls) {
    const parsed = new URL(item);
    if (parsed.protocol !== 'ldaps:' || parsed.username || parsed.password || parsed.search || parsed.hash ||
        !['','/'].includes(parsed.pathname) || Number(parsed.port || 636) !== 636) throw Error('LDAP requires LDAPS on port 636');
  }
  if (config.rejectUnauthorized === false || config.sslSkipVerify === true) throw Error('LDAP certificate verification cannot be disabled');
  if (fs.readFileSync(config.caFile).length > 1024*1024) throw Error('LDAP CA bundle exceeds limit');
  return config;
}
function defaultFactory(options) {
  const file = [path.join(__dirname, 'ldapts.cjs'), path.join(__dirname, '../vendor/ldapts/ldapts.cjs')].find(f => fs.existsSync(f));
  if (!file || crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex') !== CLIENT_SHA256) throw Error('Pinned LDAP client integrity mismatch');
  return new (require(file).Client)(options);
}
class Directory {
  constructor(configFile, {clientFactory = defaultFactory} = {}) {
    this.config = readConfig(configFile); this.clientFactory = clientFactory; this.pending = 0;
  }
  async authenticate(username, password) {
    const c = this.config, expected = normalizeUsername(username, c.domain);
    if (typeof password !== 'string' || !password.length || Buffer.byteLength(password) > 1024 || password.includes('\0')) throw denied();
    if (this.pending >= 4) throw unavailable();
    this.pending++;
    try {
      for (let i = 0; i < c.urls.length; i++) {
        let client, verifyingUser = false;
        try {
          client = this.clientFactory({url:c.urls[i], timeout:c.timeoutMs, connectTimeout:c.timeoutMs,
            strictDN:true, autoRebind:false, tlsOptions:{ca:fs.readFileSync(c.caFile), minVersion:'TLSv1.2', rejectUnauthorized:true}});
          const secret = fs.readFileSync(c.bindPasswordFile, 'utf8').replace(/\r?\n$/, '');
          if (!secret || secret.includes('\0')) throw unavailable();
          await client.bind(c.bindDN, secret);
          const entries = [];
          for (const base of c.searchBases) {
            const result = await client.search(base, {scope:'sub',
              filter:c.searchFilter.replace('%s', filterValue(expected)), sizeLimit:2,
              attributes:['sAMAccountName','objectGUID','displayName','mail','userAccountControl'],
              explicitBufferAttributes:['objectGUID']});
            entries.push(...result.searchEntries);
            // Referrals are never followed into another directory or endpoint.
          }
          if (entries.length !== 1) throw denied();
          const user = entries[0], get = name => user[Object.keys(user).find(k => k.toLowerCase() === name.toLowerCase())];
          const canonical = normalizeUsername(get('sAMAccountName'), c.domain), guid = get('objectGUID');
          if (canonical !== expected || !Buffer.isBuffer(guid) || guid.length !== 16 || typeof user.dn !== 'string' || !user.dn ||
              (Number(get('userAccountControl')) & 2)) throw denied();
          verifyingUser = true;
          await client.bind(user.dn, password);
          return {username:canonical, subject:guid.toString('hex')};
        } catch (error) {
          if (error instanceof DirectoryError) throw error;
          // Invalid credentials never fan out to other domain controllers.
          if (Number(error.code) === 49) throw verifyingUser ? denied() : unavailable();
          if (i === c.urls.length - 1) throw unavailable();
        } finally {
          if (client) try { await client.unbind(); } catch { /* No bind state is reused. */ }
        }
      }
      throw unavailable();
    } finally { this.pending--; }
  }
}
module.exports = {Directory, DirectoryError, normalizeUsername, filterValue, readConfig, CLIENT_SHA256};
