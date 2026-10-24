"use strict";
const test = require("node:test"), assert = require("node:assert/strict"), crypto = require("node:crypto");
const { createRegistryTokenService, createRegistryTokenHandler } = require("./registry_token_service");
const keys = crypto.generateKeyPairSync("rsa", { modulusLength: 2048 }); // Synthetic in-memory test keys only.
function fixture(overrides = {}) {
  const state = { enabled: true, user: "alice", authProvider: "local", accountStamp: "synthetic-account-stamp-1" };
  const calls = [];
  const options = { signingKey: keys.privateKey, issuer: "dsh.test.invalid", service: "registry.test.invalid",
    snapshotAccount: async () => ({ ...state }), loadGrants: async () => ({ alice: { "smp/pipeline": ["pull"] } }),
    authenticateIdentity: async (...args) => { calls.push(args); return { user: "alice", authProvider: "local" }; },
    now: () => 1792764000000, ...overrides };
  return { state, calls, issue: createRegistryTokenService(options) };
}
const request = { username: "alice", password: "synthetic-only", service: "registry.test.invalid", scopes: ["repository:smp/pipeline:pull,push"] };
function decode(token) { return JSON.parse(Buffer.from(token.split(".")[1], "base64url")); }

test("signs actual short-lived signature and intersects server grants", async () => {
  const f = fixture(), r = await f.issue(request), claims = decode(r.token), parts = r.token.split(".");
  assert.equal(crypto.verify("RSA-SHA256", Buffer.from(parts[0] + "." + parts[1]), keys.publicKey, Buffer.from(parts[2], "base64url")), true);
  assert.deepEqual(claims.access, [{ type: "repository", name: "smp/pipeline", actions: ["pull"] }]);
  assert.equal(claims.exp - claims.iat, 60); assert.equal(claims.aud, request.service);
  assert.deepEqual(f.calls[0].slice(2), ["local", { create: false }]);
  assert.equal(JSON.stringify(claims).includes(request.password), false);
});
test("disabled account never calls native authenticator", async () => {
  const f = fixture(); f.state.enabled = false; await assert.rejects(f.issue(request), e => e.status === 401); assert.equal(f.calls.length, 0);
});
test("account stamp change during authentication rejects token", async () => {
  let f; f = fixture({ authenticateIdentity: async () => { f.state.accountStamp = "changed-stamp-after-auth"; return { user: "alice", authProvider: "local" }; } });
  await assert.rejects(f.issue(request), e => e.status === 401);
});
test("disable during grant load rejects token", async () => {
  let f; f = fixture({ loadGrants: async () => { f.state.enabled = false; return {}; } });
  await assert.rejects(f.issue(request), e => e.status === 401);
});
test("provider is resolved from native snapshot and JIT creation prohibited", async () => {
  let f; f = fixture({ authenticateIdentity: async (...args) => { assert.equal(args[2], "ldap"); assert.deepEqual(args[3], { create: false }); return { user: "alice", authProvider: "ldap" }; } });
  f.state.authProvider = "ldap"; await f.issue({ ...request, provider: "local" });
});
test("audience and unsafe scopes reject", async () => {
  const f = fixture(); await assert.rejects(f.issue({ ...request, service: "evil.invalid" }), e => e.status === 400);
  await assert.rejects(f.issue({ ...request, scopes: ["registry:catalog:*"] }), e => e.status === 400);
});
test("empty grants create no repository access", async () => {
  const f = fixture({ loadGrants: async () => ({}) }); assert.deepEqual(decode((await f.issue(request)).token).access, []);
});
test("tokens have unique IDs", async () => {
  const f = fixture(); assert.notEqual(decode((await f.issue(request)).token).jti, decode((await f.issue(request)).token).jti);
});
async function http({ method = "GET", authorization, secure = true, allowed = true, url = "/api/registry/token?service=registry.test.invalid&scope=repository:smp/pipeline:pull" } = {}) {
  let result;
  const f = fixture(), handler = createRegistryTokenHandler({ issue: f.issue, trustedTransport: () => secure, admit: () => allowed });
  const res = { writeHead(status, headers) { result = { status, headers }; }, end(body) { result.body = JSON.parse(body); } };
  await handler({ method, url, headers: { authorization } }, res); return result;
}
const basic = "Basic " + Buffer.from("alice:synthetic-only").toString("base64");
test("handler returns signed token and no-store", async () => { const r = await http({ authorization: basic }); assert.equal(r.status, 200); assert.equal(r.headers["Cache-Control"], "no-store"); });
test("handler rejects plain transport, method and admission failure", async () => {
  assert.equal((await http({ authorization: basic, secure: false })).status, 403);
  assert.equal((await http({ authorization: basic, method: "POST" })).status, 405);
  assert.equal((await http({ authorization: basic, allowed: false })).status, 429);
});
test("handler never accepts missing cookie-only or malformed Basic identity", async () => {
  for (const authorization of [undefined, "Bearer synthetic", "Basic !!!", "Basic " + Buffer.from(":secret").toString("base64")]) assert.equal((await http({ authorization })).status, 401);
});
test("duplicate audience rejected", async () => {
  assert.equal((await http({ authorization: basic, url: "/api/registry/token?service=registry.test.invalid&service=evil.invalid" })).status, 400);
});
test("invalid UTF8 Basic is an authentication refusal, not a server error", async () => {
  assert.equal((await http({ authorization: "Basic " + Buffer.from([0xff, 0x3a, 0x61]).toString("base64") })).status, 401);
});
test("handler refuses unrelated route", async () => {
  assert.equal((await http({ authorization: basic, url: "/unrelated?service=registry.test.invalid" })).status, 404);
});
test("native DSH authenticator integration uses no real store, AD or account creation", { skip: !process.env.DSH_IDENTITY_MODULE }, async () => {
  const { createAuthenticator } = require(process.env.DSH_IDENTITY_MODULE);
  let writes = 0;
  const authenticateIdentity = createAuthenticator({ directory: null, loadUsers: () => ({ alice: { authProvider: "local" } }),
    saveUsers: () => { writes++; }, verifyPassword: async () => true,
    newAccountRecord: () => { throw new Error("Must never create"); }, isAdmin: () => false, audit: () => true });
  const f = fixture({ authenticateIdentity }); await f.issue(request); assert.equal(writes, 0);
});
test("native DSH existing LDAP account is checked with no JIT or real directory", { skip: !process.env.DSH_IDENTITY_MODULE }, async () => {
  const { createAuthenticator } = require(process.env.DSH_IDENTITY_MODULE);
  let writes = 0, directoryCalls = 0;
  const authenticateIdentity = createAuthenticator({ directory: { authenticate: async () => { directoryCalls++; return { username: "alice", subject: "synthetic-directory-subject" }; } },
    loadUsers: () => ({ alice: { authProvider: "ldap", ldapSubject: "synthetic-directory-subject" } }),
    saveUsers: () => { writes++; }, verifyPassword: () => { throw new Error("No local verifier for directory account"); },
    newAccountRecord: () => { throw new Error("Must never create"); }, isAdmin: () => false, audit: () => true });
  const f = fixture({ authenticateIdentity }); f.state.authProvider = "ldap";
  await f.issue(request); assert.equal(writes, 0); assert.equal(directoryCalls, 1);
});

test("RSA JWK kid independently equals the RFC 7638 trusted-certificate key thumbprint", async () => {
  const r = await fixture().issue(request);
  const header = JSON.parse(Buffer.from(r.token.split(".")[0], "base64url"));
  const exported = keys.publicKey.export({ format: "jwk" });
  const canonical = '{"e":"' + exported.e + '","kty":"RSA","n":"' + exported.n + '"}';
  const expected = crypto.createHash("sha256").update(canonical, "utf8").digest("base64url");
  assert.equal(header.kid, expected); assert.equal(header.jwk.kid, expected);
  assert.equal(crypto.createPublicKey({ key: header.jwk, format: "jwk" }).export({ format: "pem", type: "spki" }), keys.publicKey.export({ format: "pem", type: "spki" }));
  assert.equal(Object.hasOwn(header.jwk, "d"), false);
});
