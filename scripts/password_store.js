'use strict';
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const parameters = { N: 32768, r: 8, p: 1, maxmem: 64 * 1024 * 1024 };
function isPasswordRecord(value) {
  return value && value.scheme === 'scrypt-v1' && /^[a-f0-9]{32}$/.test(value.salt) && /^[a-f0-9]{64}$/.test(value.hash);
}
function hashPassword(password) {
  if (typeof password !== 'string' || !password.length || Buffer.byteLength(password) > 1024) throw new Error('Invalid password length');
  const salt = crypto.randomBytes(16).toString('hex');
  return { scheme: 'scrypt-v1', salt, hash: crypto.scryptSync(password, Buffer.from(salt, 'hex'), 32, parameters).toString('hex') };
}
const dummy = hashPassword(crypto.randomBytes(32).toString('hex'));
let pending = 0;
async function verifyPassword(password, record) {
  if (typeof password !== 'string' || Buffer.byteLength(password) > 1024 || pending >= 4) return false;
  const valid = isPasswordRecord(record) && (!record.authProvider || record.authProvider === 'local');
  const target = valid ? record : dummy;
  pending++;
  try {
    const actual = await new Promise((resolve, reject) => crypto.scrypt(password, Buffer.from(target.salt, 'hex'), 32, parameters,
      (error, key) => error ? reject(error) : resolve(key)));
    return crypto.timingSafeEqual(actual, Buffer.from(target.hash, 'hex')) && Boolean(valid);
  } catch { return false; }
  finally { pending--; }
}
function migrateUsers(users) {
  if (!users || typeof users !== 'object' || Array.isArray(users)) throw new Error('Invalid account store');
  const result = Object.create(null);
  for (const [name, value] of Object.entries(users)) {
    if (!/^[a-zA-Z0-9_.-]{1,30}$/.test(name)) throw new Error('Invalid stored account name');
    if (typeof value === 'string') result[name] = hashPassword(value);
    else if (isPasswordRecord(value)) result[name] = value;
    else throw new Error('Invalid password record');
  }
  return result;
}
function writeAtomicUsers(file, users) {
  if (Object.values(users).some(value => !isPasswordRecord(value))) throw new Error('Refusing plaintext account write');
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const temporary = file + '.tmp-' + crypto.randomBytes(12).toString('hex');
  let fd;
  try {
    fd = fs.openSync(temporary, 'wx', 0o600);
    fs.writeFileSync(fd, JSON.stringify(users, null, 2)); fs.fsyncSync(fd); fs.closeSync(fd); fd = undefined;
    fs.renameSync(temporary, file); fs.chmodSync(file, 0o600);
  } finally {
    if (fd !== undefined) fs.closeSync(fd);
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
  }
}
module.exports = { hashPassword, verifyPassword, isPasswordRecord, migrateUsers, writeAtomicUsers };
