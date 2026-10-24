"use strict";
// Pure policy core, not an HTTP authentication endpoint or token issuer.
// principal and grants MUST come from the verified server-side DSH adapter.
const component = "[a-z0-9]+(?:(?:[._]|__|[-]+)[a-z0-9]+)*";
const repositoryPattern = new RegExp(`^${component}(?:/${component})*$`);
const actionsAllowed = new Set(["pull", "push"]);
function authorizeRegistryScopes({ principal, service, expectedService, requestedScopes, grants }) {
  if (!principal || principal.authenticated !== true || principal.enabled !== true || typeof principal.id !== "string" || !principal.id || principal.id.length > 128) throw new Error("Verified enabled principal required");
  if (typeof service !== "string" || !service || service !== expectedService) throw new Error("Registry audience mismatch");
  if (!Array.isArray(requestedScopes) || requestedScopes.length > 16 || !grants || typeof grants !== "object") throw new Error("Invalid bounded scope request");
  const policy = Object.hasOwn(grants, principal.id) ? grants[principal.id] : {};
  const access = new Map();
  for (const scope of requestedScopes) {
    if (typeof scope !== "string" || scope.length > 512) throw new Error("Invalid scope");
    const match = /^repository:([^:]+):([^:]+)$/.exec(scope);
    // Hosted-registry repository paths only. Host:port names/catalog/plugins are not enabled.
    if (!match || !repositoryPattern.test(match[1])) throw new Error("Unsupported resource scope");
    const requested = match[2].split(",");
    if (!requested.length || requested.some(a => !actionsAllowed.has(a))) throw new Error("Unsupported repository action");
    const permitted = Object.hasOwn(policy, match[1]) ? policy[match[1]] : [];
    if (!Array.isArray(permitted) || permitted.some(a => !actionsAllowed.has(a))) throw new Error("Invalid server policy");
    const approved = access.get(match[1]) || new Set();
    for (const action of requested) if (permitted.includes(action)) approved.add(action);
    if (approved.size) access.set(match[1], approved);
  }
  return { subject: principal.id, audience: service, access: [...access.entries()].map(([name, actions]) => ({ type: "repository", name, actions: [...actions].sort() })) };
}
module.exports = { authorizeRegistryScopes };
