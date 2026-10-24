"use strict";
// Dedicated token listener; importing this module never binds a port or reads a key/account store.
const https = require("node:https"), net = require("node:net");
const { createMachineTokenService } = require("./registry_machine_service");
const { createRegistryTokenService, createRegistryTokenHandler } = require("./registry_token_service");
function createTokenHttpsServer({ native, readMachinePrincipals = () => ({}), signingKey, tlsKey, tlsCert, issuer, service, allowedPeers,
    now = () => Date.now(), perMinute = 30, maxPeers = 128 }) {
  if (!Array.isArray(allowedPeers) || !allowedPeers.length || allowedPeers.some(x => typeof x !== "string" || net.isIP(x) === 0))
    throw Error("Explicit exact trusted peer IP allowlist required");
  if (!Number.isInteger(perMinute) || perMinute < 1 || perMinute > 120 || !Number.isInteger(maxPeers) || maxPeers < 1 || maxPeers > 256)
    throw Error("Invalid admission bounds");
  const peers = new Set(allowedPeers), attempts = new Map();
  const humanIssue = createRegistryTokenService({ ...native, signingKey, issuer, service });
  const machineIssue = createMachineTokenService({ readPrincipals: readMachinePrincipals, signingKey, issuer, service });
  const issue = r => r.username.startsWith("robot~") ? machineIssue(r) : humanIssue(r);
  const handler = createRegistryTokenHandler({ issue, trustedTransport: req => req.socket.encrypted === true,
    admit: req => {
      const peer = req.socket.remoteAddress; if (!peers.has(peer)) return false;
      const time = now();
      for (const [key, value] of attempts) if (time - value.start >= 60000) attempts.delete(key);
      if (!attempts.has(peer)) { if (attempts.size >= maxPeers) return false; attempts.set(peer, { start: time, count: 0 }); }
      return ++attempts.get(peer).count <= perMinute;
    } });
  const server = https.createServer({ key: tlsKey, cert: tlsCert, minVersion: "TLSv1.2", maxHeaderSize: 8192 }, (req, res) => {
    req.resume(); // GET token API never consumes a request body.
    Promise.resolve(handler(req, res)).catch(() => { if (!res.headersSent) res.writeHead(503); res.end(); });
  });
  server.requestTimeout = 15000; server.headersTimeout = 10000; server.keepAliveTimeout = 5000; server.maxConnections = 32;
  server.on("clientError", (_error, socket) => socket.end("HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n"));
  return server;
}
module.exports = { createTokenHttpsServer };
