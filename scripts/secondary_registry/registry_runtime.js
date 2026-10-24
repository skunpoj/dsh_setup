"use strict";
// Explicit CLI entry point for a NEW isolated token Deployment; no existing DSH gateway edit.
const fs = require("node:fs"), path = require("node:path"), crypto = require("node:crypto");
const { createNativeBridge } = require("./registry_native_bridge");
const { createTokenHttpsServer } = require("./registry_token_https");
function readBounded(file, max) {
  if (!path.isAbsolute(file)) throw Error("Protected file references must be absolute");
  if (fs.lstatSync(file).isSymbolicLink()) throw Error("Protected file must be a directly mounted regular file");
  const fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0));
  try { const s = fs.fstatSync(fd); if (!s.isFile() || s.size > max) throw Error("Protected file exceeds bound"); return fs.readFileSync(fd); }
  finally { fs.closeSync(fd); }
}
function createRuntime(config) {
  if (!config || config.version !== 1 || !["machine-only", "native-and-machine"].includes(config.mode)) throw Error("Explicit registry authentication mode required");
  const readJson = file => JSON.parse(readBounded(file, 4 * 1024 * 1024));
  let native = { authenticateIdentity: async () => null, snapshotAccount: () => null, loadGrants: () => ({}) };
  if (config.mode === "native-and-machine") {
    if (!Array.isArray(config.adminUsers) || !config.nativeSourceHashes || !path.isAbsolute(config.nativeSourceRoot)) throw Error("Native source binding required");
    for (const name of ["identity_auth.js", "password_store.js", "ldap_auth.js"]) {
      const bytes = readBounded(path.join(config.nativeSourceRoot, name), 1024 * 1024);
      if (!/^[a-f0-9]{64}$/.test(config.nativeSourceHashes[name] || "") || crypto.createHash("sha256").update(bytes).digest("hex") !== config.nativeSourceHashes[name]) throw Error("Native source binding differs");
    }
    const identity = require(path.join(config.nativeSourceRoot, "identity_auth.js"));
    const passwords = require(path.join(config.nativeSourceRoot, "password_store.js"));
    const { Directory } = require(path.join(config.nativeSourceRoot, "ldap_auth.js"));
    const directory = config.directoryConfigPath ? new Directory(config.directoryConfigPath) : null;
    native = createNativeBridge({ identity, passwords, directory, readUsers: () => readJson(config.userStorePath),
      readGrants: () => readJson(config.grantsPath), isAdmin: user => config.adminUsers.includes(user),
      audit: event => { if (!/^login\.[a-z-]+$/.test(event)) throw Error("Invalid audit category"); process.stderr.write(JSON.stringify({ component: "registry-native-auth", event }) + "\n"); } });
  }
  const signingKey = crypto.createPrivateKey(readBounded(config.signingKeyPath, 16384));
  return createTokenHttpsServer({ native, readMachinePrincipals: () => readJson(config.machinePrincipalsPath), signingKey, tlsKey: readBounded(config.tlsKeyPath, 16384),
    tlsCert: readBounded(config.tlsCertPath, 65536), issuer: config.issuer, service: config.service,
    allowedPeers: config.allowedPeers, perMinute: config.perMinute || 30 });
}
function main() {
  if (process.argv.length !== 3) throw Error("Supply one protected runtime config path");
  const config = JSON.parse(readBounded(path.resolve(process.argv[2]), 65536));
  if (!["127.0.0.1", "0.0.0.0"].includes(config.bindHost) || !Number.isInteger(config.port) || config.port < 1024 || config.port > 65535) throw Error("Explicit listener address required");
  const server = createRuntime(config); server.listen(config.port, config.bindHost);
  for (const sig of ["SIGTERM", "SIGINT"]) process.once(sig, () => { server.close(() => process.exit(0)); setTimeout(() => process.exit(1), 10000).unref(); });
}
if (require.main === module) { try { main(); } catch { process.stderr.write("Registry token runtime configuration refused\n"); process.exitCode = 1; } }
module.exports = { createRuntime, readBounded };
