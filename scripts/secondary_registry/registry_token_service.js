"use strict";
// Local candidate: inject the EXISTING DSH identity and current account policy.
// No password store, file reads, network calls, key provisioning or server startup.
const { createJwtSigner } = require("./registry_jwt_signer");
const { authorizeRegistryScopes } = require("./registry_scope_policy");

class TokenError extends Error {
  constructor(status) {
    super(status === 401 ? "Registry authentication required" : "Registry token unavailable");
    this.status = status;
  }
}

function createRegistryTokenService(options) {
  const {
    authenticateIdentity, snapshotAccount, loadGrants, signingKey,
    issuer, service, lifetimeSeconds = 60, now = () => Date.now(),
  } = options;
  for (const fn of [authenticateIdentity, snapshotAccount, loadGrants, now]) {
    if (typeof fn !== "function") throw new Error("Native server-side identity adapter required");
  }
  const sign = createJwtSigner({ signingKey, issuer, service, lifetimeSeconds, now });
  const validSnapshot = s => Boolean(s && s.enabled === true &&
    typeof s.user === "string" && s.user.length > 0 && s.user.length <= 128 &&
    ["local", "ldap"].includes(s.authProvider) &&
    typeof s.accountStamp === "string" && s.accountStamp.length >= 16);

  return async function issue(request) {
    if (!request || request.service !== service || !Array.isArray(request.scopes) || request.scopes.length > 16) throw new TokenError(400);
    const { username, password } = request;
    if (typeof username !== "string" || !username || Buffer.byteLength(username) > 256 ||
        typeof password !== "string" || !password || Buffer.byteLength(password) > 1024) throw new TokenError(401);
    // Account/provider/stamp must be resolved by native DSH callbacks, never query fields.
    const before = await snapshotAccount(username);
    if (!validSnapshot(before)) throw new TokenError(401);
    const identity = await authenticateIdentity(username, password, before.authProvider, { create: false });
    const after = await snapshotAccount(before.user);
    if (!identity || identity.user !== before.user || identity.authProvider !== before.authProvider ||
        !validSnapshot(after) || after.user !== before.user || after.authProvider !== before.authProvider ||
        after.accountStamp !== before.accountStamp) throw new TokenError(401);
    let authorized;
    try {
      authorized = authorizeRegistryScopes({
        principal: { id: after.user, authenticated: true, enabled: true },
        service: request.service, expectedService: service,
        requestedScopes: request.scopes, grants: await loadGrants(),
      });
    } catch { throw new TokenError(400); }
    // Grants may be loaded asynchronously: recheck native account revocation after that await.
    const final = await snapshotAccount(after.user);
    if (!validSnapshot(final) || final.user !== after.user || final.accountStamp !== after.accountStamp ||
        final.authProvider !== after.authProvider) throw new TokenError(401);
    return sign(authorized);
  };
}

function parseBasic(header) {
  if (typeof header !== "string" || header.length > 4096 || !/^Basic [A-Za-z0-9+/]+={0,2}$/.test(header)) throw new TokenError(401);
  const encoded = header.slice(6), bytes = Buffer.from(encoded, "base64");
  if (bytes.toString("base64") !== encoded) throw new TokenError(401);
  let decoded;
  try { decoded = new TextDecoder("utf-8", { fatal: true }).decode(bytes); }
  catch { throw new TokenError(401); }
  if (/[\x00-\x1f\x7f]/.test(decoded)) throw new TokenError(401);
  const colon = decoded.indexOf(":");
  if (colon <= 0) throw new TokenError(401);
  return { username: decoded.slice(0, colon), password: decoded.slice(colon + 1) };
}

function createRegistryTokenHandler({ issue, trustedTransport, admit }) {
  if (![issue, trustedTransport, admit].every(fn => typeof fn === "function")) throw new Error("Explicit trusted transport and admission callbacks required");
  return async function handle(req, res) {
    const headers = { "Cache-Control": "no-store", Pragma: "no-cache",
      "Content-Type": "application/json; charset=utf-8", "X-Content-Type-Options": "nosniff" };
    function send(status, body, extra = {}) { res.writeHead(status, { ...headers, ...extra }); res.end(JSON.stringify(body)); }
    try {
      // No browser-cookie authentication or caller-supplied forwarded-header trust.
      if (req.method !== "GET") return send(405, { error: "Method not allowed" }, { Allow: "GET" });
      if (trustedTransport(req) !== true) return send(403, { error: "Secure transport required" });
      if (admit(req) !== true) return send(429, { error: "Request limit reached" }, { "Retry-After": "60" });
      if (typeof req.url !== "string" || req.url.length > 8192) throw new TokenError(400);
      const parsed = new URL(req.url, "https://registry-token.invalid");
      if (parsed.pathname !== "/api/registry/token") throw new TokenError(404);
      if (parsed.searchParams.getAll("service").length !== 1) throw new TokenError(400);
      const credentials = parseBasic(req.headers.authorization);
      const result = await issue({ ...credentials, service: parsed.searchParams.get("service"), scopes: parsed.searchParams.getAll("scope") });
      return send(200, result);
    } catch (error) {
      const status = error instanceof TokenError ? error.status : 503;
      return send(status, { error: status === 401 ? "Authentication required" : "Registry token unavailable" },
        status === 401 ? { "WWW-Authenticate": 'Basic realm="DSH registry token"' } : {});
    }
  };
}

module.exports = { createRegistryTokenService, createRegistryTokenHandler, TokenError };
