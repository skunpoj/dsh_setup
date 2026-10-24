"use strict";
// Read-only bridge around the actual DSH identity/password modules. No account creation or writes.
const crypto = require("node:crypto");
function createNativeBridge({ identity, passwords, directory = null, readUsers, readGrants, isAdmin, audit }) {
  if (typeof identity?.createAuthenticator !== "function" || typeof passwords?.verifyPassword !== "function" ||
      [readUsers, readGrants, isAdmin, audit].some(x => typeof x !== "function")) throw Error("Explicit native DSH dependencies required");
  const prohibited = () => { throw Error("Registry cannot create or write DSH accounts"); };
  const authenticateIdentity = identity.createAuthenticator({ directory, loadUsers: readUsers, saveUsers: prohibited,
    verifyPassword: passwords.verifyPassword, newAccountRecord: prohibited, isAdmin, audit });
  function snapshotAccount(input) {
    if (typeof input !== "string" || input.length > 256) return null;
    let name = input.trim().toLowerCase();
    if (name.includes("@") || name.includes("\\")) return null; // Canonical DSH username only; no caller-selected provider/domain.
    const users = readUsers();
    if (!users || typeof users !== "object" || Array.isArray(users) || !Object.hasOwn(users, name)) return null;
    const a = users[name]; if (!a || a.disabled === true) return null;
    const authProvider = a.authProvider === "ldap" ? "ldap" : "local";
    // Exactly the existing gateway sessionAccountStamp fields; no password/hash leaves this closure.
    const stamp = authProvider === "ldap" ? ["ldap", a.ldapSubject, a.scheme, a.salt, a.hash] : [a.scheme, a.salt, a.hash];
    return { user: name, authProvider, enabled: true,
      accountStamp: crypto.createHash("sha256").update(JSON.stringify(stamp)).digest("hex") };
  }
  return { authenticateIdentity, snapshotAccount, loadGrants: readGrants };
}
module.exports = { createNativeBridge };
