"use strict";
// Machine identities are NEW scoped registry clients; never DSH human accounts or copied admin credentials.
const crypto = require("node:crypto");
const { createJwtSigner } = require("./registry_jwt_signer");
const { authorizeRegistryScopes } = require("./registry_scope_policy");
const { TokenError } = require("./registry_token_service");
function createMachineTokenService({ readPrincipals, signingKey, issuer, service, now = () => Date.now() }) {
  if (typeof readPrincipals !== "function") throw Error("Protected machine-principal loader required");
  const sign = createJwtSigner({ signingKey, issuer, service, now });
  function lookup(store, id) {
    if (!store || typeof store !== "object" || !Object.hasOwn(store, id)) return null;
    const p = store[id];
    return p && p.enabled === true && typeof p.rotationStamp === "string" && /^[a-f0-9]{32,128}$/.test(p.rotationStamp) &&
      typeof p.secretSha256 === "string" && /^[a-f0-9]{64}$/.test(p.secretSha256) && p.grants && typeof p.grants === "object" ? { enabled: true, rotationStamp: p.rotationStamp, secretSha256: p.secretSha256, grants: structuredClone(p.grants) } : null;
  }
  const same = (a, b) => a && b && a.rotationStamp === b.rotationStamp && a.secretSha256 === b.secretSha256;
  return async function issue(request) {
    if (!request || request.service !== service || !Array.isArray(request.scopes) || request.scopes.length > 16) throw new TokenError(400);
    const { username, password } = request;
    if (typeof username !== "string" || !/^robot~[a-z0-9][a-z0-9-]{2,62}$/.test(username) ||
        typeof password !== "string" || password.length < 32 || Buffer.byteLength(password) > 256) throw new TokenError(401);
    const before = lookup(await readPrincipals(), username);
    const actual = crypto.createHash("sha256").update(password).digest();
    const expected = Buffer.from(before ? before.secretSha256 : "0".repeat(64), "hex");
    const verified = crypto.timingSafeEqual(actual, expected);
    if (!verified || !before) throw new TokenError(401);
    const after = lookup(await readPrincipals(), username); if (!same(before, after)) throw new TokenError(401);
    let access;
    try { access = authorizeRegistryScopes({ principal: { id: username, authenticated: true, enabled: true }, service, expectedService: service,
      requestedScopes: request.scopes, grants: { [username]: after.grants } }); } catch { throw new TokenError(400); }
    const final = lookup(await readPrincipals(), username);
    if (!same(after, final) || JSON.stringify(after.grants) !== JSON.stringify(final.grants)) throw new TokenError(401);
    return sign(access);
  };
}
module.exports = { createMachineTokenService };
