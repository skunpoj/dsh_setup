'use strict';

class CancelBoundaryError extends Error {
  constructor(code) { super(code); this.code = code; }
}
const fail = code => { throw new CancelBoundaryError(code); };

function createCancellationController(deps) {
  const required = {journal:['fence','active','finish'], broker:['revoke','fence'], transport:['stop','fence'], supervisor:['stopExact','verifyAbsent']};
  for (const [name, methods] of Object.entries(required)) {
    if (!deps[name] || methods.some(method => typeof deps[name][method] !== 'function')) fail('MISSING_' + name.toUpperCase());
  }
  const bound = Object.freeze(Object.fromEntries(Object.entries(required).map(([name, methods]) => [name, Object.freeze(Object.fromEntries(methods.map(method => [method, deps[name][method].bind(deps[name])])))])));
  const states = new Map();

  async function cancel(context, reason) {
    if (!context || !context.bindingId || !context.workerUID || !context.sessionGeneration || !context.subjectUser) fail('INVALID_CONTEXT');
    if (!['user-cancel','logout','revocation'].includes(reason)) fail('INVALID_REASON');
    const frozen = Object.freeze({subjectUser:context.subjectUser, sessionGeneration:context.sessionGeneration, bindingId:context.bindingId, workerUID:context.workerUID});
    const key = [frozen.subjectUser, frozen.sessionGeneration, frozen.bindingId, frozen.workerUID].join(':');
    let state = states.get(key);
    if (state?.complete) fail('REPLAY_REFUSED');
    if (!state) {
      state = {context:frozen, reason, operationId:'cancel-'+key, phase:0, complete:false, running:null};
      states.set(key,state);
    } else if (state.reason !== reason || JSON.stringify(state.context) !== JSON.stringify(frozen)) fail('CANCEL_CONTEXT_CHANGED');
    if (state.running) return state.running;
    state.running = (async () => {
      const args = Object.freeze({...frozen, reason, operationId:state.operationId});
      if (state.phase < 1) {
        const active = await bound.journal.active(Object.freeze({subjectUser:frozen.subjectUser, sessionGeneration:frozen.sessionGeneration}));
        if (!Array.isArray(active) || !active.some(entry => entry.bindingId === frozen.bindingId && entry.workerUID === frozen.workerUID && entry.ownerUser === frozen.subjectUser && entry.workerGeneration === frozen.sessionGeneration)) fail('NO_EXACT_ACTIVE_BINDING');
        state.phase = 1;
      }
      if (state.phase < 2) { const receipt = await bound.journal.fence(args); if (!receipt || receipt.fenced !== true || receipt.operationId !== state.operationId) fail('JOURNAL_FENCE_UNVERIFIED'); state.phase = 2; }
      if (state.phase < 3) { const receipt = await bound.broker.revoke(args); if (!receipt || receipt.bindingId !== frozen.bindingId || receipt.revoked !== true || receipt.operationId !== state.operationId) fail('BROKER_REVOCATION_UNVERIFIED'); state.phase = 3; }
      if (state.phase < 4) { const receipt = await bound.broker.fence(args); if (!receipt || receipt.fenced !== true || receipt.operationId !== state.operationId) fail('BROKER_FENCE_UNVERIFIED'); state.phase = 4; }
      if (state.phase < 5) { const receipt = await bound.transport.fence(args); if (!receipt || receipt.fenced !== true || receipt.operationId !== state.operationId) fail('TRANSPORT_FENCE_UNVERIFIED'); state.phase = 5; }
      if (state.phase < 6) { const receipt = await bound.transport.stop(args); if (!receipt || receipt.bindingId !== frozen.bindingId || receipt.workerUID !== frozen.workerUID || receipt.stopped !== true || receipt.operationId !== state.operationId) fail('WORKLOAD_STOP_UNVERIFIED'); state.phase = 6; }
      if (state.phase < 7) { const receipt = await bound.supervisor.stopExact(args); if (!receipt || receipt.bindingId !== frozen.bindingId || receipt.workerUID !== frozen.workerUID || receipt.stopped !== true || receipt.operationId !== state.operationId) fail('SUPERVISOR_STOP_UNVERIFIED'); state.phase = 7; }
      if (state.phase < 8) { const receipt = await bound.supervisor.verifyAbsent(args); if (!receipt || receipt.absent !== true || receipt.workerUID !== frozen.workerUID || receipt.operationId !== state.operationId) fail('ABSENCE_UNVERIFIED'); state.phase = 8; }
      if (state.phase < 9) { const receipt = await bound.journal.finish(Object.freeze({...args,outcome:'cancelled'})); if (!receipt || receipt.finished !== true || receipt.operationId !== state.operationId) fail('JOURNAL_FINISH_UNVERIFIED'); state.phase = 9; }
      state.complete = true;
      return Object.freeze({bindingId:frozen.bindingId, workerUID:frozen.workerUID, reason, operationId:state.operationId, brokerRevoked:true, workloadStopped:true, supervisorStopped:true, absent:true});
    })();
    try { return await state.running; } finally { state.running = null; }
  }

  function assertNoFallback(result) {
    if (!result || result.unrestrictedFallback !== false || result.nativeRequired !== true) fail('UNRESTRICTED_FALLBACK');
    return true;
  }

  return Object.freeze({cancel, assertNoFallback});
}

module.exports = {createCancellationController, CancelBoundaryError};
