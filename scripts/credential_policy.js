'use strict';
// Broker policy contract only. This module never stores or resolves secret values.
const crypto = require('node:crypto');
function denied() { throw new Error('Credential use denied'); }
function authorizeCredentialUse({principal, environment, workspace, credential, request, approval, now = Date.now()}) {
  if (!principal || !workspace || !['off','on'].includes(environment)) denied();
  if (!credential || credential.owner !== principal || credential.revoked ||
      !Number.isFinite(credential.expiresAt) || credential.expiresAt <= now ||
      !credential.environments?.includes(environment) || !credential.workspaces?.includes(workspace)) denied();
  const rule = credential.rules?.find(r => r.connector === request?.connector && r.operation === request?.operation && r.resource === request?.resource);
  if (!rule) denied();
  // Broker connectors must pin and resolve destinations independently; never fetch a caller URL.
  if (rule.requiresApproval && (!approval || approval.owner !== principal ||
      approval.credentialId !== credential.id || approval.operation !== request.operation ||
      approval.resource !== request.resource || approval.workspace !== workspace ||
      approval.environment !== environment || approval.requestDigest !== request.digest ||
      !/^[a-f0-9]{64}$/.test(request.digest || '') ||
      !Number.isFinite(approval.expiresAt) || approval.expiresAt <= now || approval.used)) denied();
  return Object.freeze({owner:principal, environment, workspace, credentialId:credential.id,
    connector:rule.connector, operation:rule.operation, resource:rule.resource,
    // Stable identifiers only: never include request content or secret material in audit output.
    auditId:crypto.randomUUID()});
}
module.exports = {authorizeCredentialUse};
