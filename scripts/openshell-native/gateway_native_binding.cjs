'use strict';

class GatewayBoundaryError extends Error {
  constructor(code) { super(code); this.code = code; }
}

const fail = code => { throw new GatewayBoundaryError(code); };
const opaque = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value);
const exactKeys = (value, keys) => value && Object.keys(value).sort().join(',') === [...keys].sort().join(',');

function bindNativeRequest({session, request, task, trustedServerOrigin, now = Date.now()}) {
  if (!exactKeys(session, ['csrfDigest','expiresAt','generation','sessionId','subjectUser'])) fail('INVALID_SESSION_SHAPE');
  if (!exactKeys(request, ['audience','csrfDigest','environment','requestId','route','serverOrigin'])) fail('INVALID_REQUEST_SHAPE');
  if (!exactKeys(task, ['bindingId','ownerUser','projectId','taskId','workerGeneration','workerUID'])) fail('INVALID_TASK_SHAPE');
  if (![session.sessionId, session.subjectUser, session.generation, request.requestId, task.bindingId, task.projectId, task.taskId, task.workerGeneration, task.workerUID].every(opaque)) fail('INVALID_OPAQUE_ID');
  if (!Number.isSafeInteger(session.expiresAt) || !(now < session.expiresAt) || session.expiresAt - now > 300000) fail('SESSION_EXPIRED_OR_TOO_LONG');
  if (!/^[a-f0-9]{64}$/.test(session.csrfDigest) || !/^[a-f0-9]{64}$/.test(request.csrfDigest)) fail('INVALID_CSRF_DIGEST');
  let trusted;
  try { trusted = new URL(trustedServerOrigin); } catch { fail('INVALID_TRUSTED_ORIGIN'); }
  if (trusted.protocol !== 'https:' || trusted.username || trusted.password || trusted.pathname !== '/' || trusted.search || trusted.hash || request.serverOrigin !== trusted.origin) fail('UNTRUSTED_SERVER_ORIGIN');
  if (request.environment !== 'secure' || request.audience !== 'dsh-openshell-test' || request.route !== 'complete-worker') fail('UNTRUSTED_ROUTE');
  if (request.csrfDigest !== session.csrfDigest) fail('CSRF_MISMATCH');
  if (task.ownerUser !== session.subjectUser || task.workerGeneration !== session.generation) fail('CROSS_OWNER_OR_STALE_GENERATION');
  return Object.freeze({
    subjectUser: session.subjectUser,
    sessionGeneration: session.generation,
    environment: request.environment,
    projectId: task.projectId,
    taskId: task.taskId,
    requestId: request.requestId,
    bindingId: task.bindingId,
    workerUID: task.workerUID,
    expiresAt: session.expiresAt,
    audience: request.audience,
    route: request.route,
  });
}

function assertCurrentBinding(context, current) {
  if (!context || !current || context.subjectUser !== current.ownerUser || context.sessionGeneration !== current.workerGeneration || context.bindingId !== current.bindingId || context.workerUID !== current.workerUID) fail('BINDING_CHANGED');
  return true;
}

module.exports = {bindNativeRequest, assertCurrentBinding, GatewayBoundaryError};
