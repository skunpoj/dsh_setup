'use strict';
const crypto = require('node:crypto');
const {DirectoryError} = require('./ldap_auth');
const collisionMessage = 'An existing locally created DSH account uses this AD username. Contact an administrator to delete the locally created account before signing in with AD. No account, files or history have been changed.';
function createAuthenticator({directory, loadUsers, saveUsers, verifyPassword, newAccountRecord, isAdmin, audit}) {
  return async function authenticate(input, password, provider, {create = true} = {}) {
    if (!['local','ldap'].includes(provider)) throw new DirectoryError('INVALID_AUTH_PROVIDER', 400, 'Choose AD or local sign-in.');
    if (provider === 'local') {
      const name = typeof input === 'string' ? input.trim().toLowerCase() : '', users = loadUsers();
      const account = Object.hasOwn(users, name) ? users[name] : null;
      if (account?.authProvider === 'ldap' || account?.disabled === true || !await verifyPassword(typeof password==='string'?password.trim():password, account)) return null;
      return {user:name, authProvider:'local'};
    }
    if (!directory) throw new DirectoryError('LDAP_DISABLED', 503, 'AD sign-in is not configured.');
    const identity = await directory.authenticate(input, password), name = identity.username;
    // Reload after the network await; a concurrent local creation must win over JIT.
    const users = loadUsers(), matches = Object.keys(users).filter(k => k.toLowerCase() === name);
    if (matches.some(k => users[k].authProvider !== 'ldap') || isAdmin(name)) {
      audit('login.identity-conflict', name);
      throw new DirectoryError('LDAP_LOCAL_ACCOUNT_CONFLICT', 409, collisionMessage);
    }
    if (matches.length > 1 || (matches.length===1 && matches[0]!==name)) throw new DirectoryError('LDAP_IDENTITY_CONFLICT', 409, 'Account identity conflict. Contact the administrator.');
    const record = users[name];
    if (record) {
      if (record.disabled === true || record.ldapSubject !== identity.subject) return null;
      return {user:name, authProvider:'ldap'};
    }
    if (!create) return null;
    if (directory.config?.allowSignUp !== true) throw new DirectoryError('LDAP_SIGNUP_DISABLED', 403, 'AD account creation is disabled. Contact the administrator.');
    // No directory password is hashed, saved or passed to a worker.
    const created = newAccountRecord(users, name, crypto.randomBytes(48).toString('hex'));
    if (created.error) throw new DirectoryError('LDAP_WORKSPACE_UNAVAILABLE', created.status, created.error);
    users[name] = {...created.record, authProvider:'ldap', ldapSubject:identity.subject, internetAllowed:false};
    if (!audit('account.ldap-created', name) || !saveUsers(users)) throw new DirectoryError('ACCOUNT_STORAGE_UNAVAILABLE', 503, 'Account storage is unavailable. Retry later.');
    return {user:name, authProvider:'ldap'};
  };
}
module.exports = {createAuthenticator, collisionMessage};
