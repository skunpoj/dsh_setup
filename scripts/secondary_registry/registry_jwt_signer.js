"use strict";
const crypto = require("node:crypto");
function createJwtSigner({ signingKey, issuer, service, lifetimeSeconds = 60, now = () => Date.now() }) {
  if (!(signingKey instanceof crypto.KeyObject) || signingKey.type !== "private" ||
      signingKey.asymmetricKeyType !== "rsa" || signingKey.asymmetricKeyDetails.modulusLength < 2048) {
    throw new Error("Approved RSA private KeyObject required");
  }
  if (![issuer, service].every(s => typeof s === "string" && /^[a-z0-9][a-z0-9.:-]{0,252}$/.test(s))) {
    throw new Error("Explicit issuer and service required");
  }
  if (!Number.isInteger(lifetimeSeconds) || lifetimeSeconds < 15 || lifetimeSeconds > 120) {
    throw new Error("Token lifetime must be 15 to 120 seconds");
  }
  const publicJwk = crypto.createPublicKey(signingKey).export({ format: "jwk" });
  // RFC 7638 canonical RSA public members; Distribution indexes trusted cert keys by this thumbprint.
  publicJwk.kid = crypto.createHash("sha256").update(JSON.stringify({ e: publicJwk.e, kty: publicJwk.kty, n: publicJwk.n })).digest("base64url");
  const headers = { typ: "JWT", alg: "RS256", kid: publicJwk.kid, jwk: publicJwk };
  return function sign(authorized) {
    const issued = Math.floor(now() / 1000);
    if (!Number.isSafeInteger(issued) || issued <= 0) throw Object.assign(new Error("Invalid token clock"), { status: 503 });
    const claims = { iss: issuer, sub: authorized.subject, aud: authorized.audience,
      iat: issued, nbf: issued, exp: issued + lifetimeSeconds,
      jti: crypto.randomBytes(18).toString("base64url"), access: authorized.access };
    const encode = value => Buffer.from(JSON.stringify(value)).toString("base64url");
    const input = encode(headers) + "." + encode(claims);
    const signature = crypto.sign("RSA-SHA256", Buffer.from(input), signingKey).toString("base64url");
    return { token: input + "." + signature, expires_in: lifetimeSeconds,
      issued_at: new Date(issued * 1000).toISOString() };
  };
}
module.exports = { createJwtSigner };
