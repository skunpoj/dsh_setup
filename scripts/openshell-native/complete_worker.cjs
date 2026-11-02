'use strict';

const crypto = require('crypto');
const path = require('path');
const {bindNativeRequest, assertCurrentBinding} = require('./gateway_native_binding.cjs');
const {createCancellationController} = require('./broker_cancel_controller.cjs');

const exactKeys = (value, keys) => value && !Array.isArray(value) && Object.keys(value).sort().join(',') === [...keys].sort().join(',');
const json = (res, status, value) => {
  res.writeHead(status, {'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});
  res.end(JSON.stringify(value));
};

function bindDependencies(deps) {
  for (const name of ['resolveTask','currentBinding','dispatch']) if (typeof deps[name] !== 'function') throw Error('OpenShell dependency missing '+name);
  return Object.freeze({
    resolveTask:deps.resolveTask.bind(deps),
    currentBinding:deps.currentBinding.bind(deps),
    dispatch:deps.dispatch.bind(deps),
    cancellation:createCancellationController(deps.cancellation || {}),
  });
}

function loadDependencies(enabled, dependencyPath) {
  if (!enabled) return null;
  if (!dependencyPath || !path.isAbsolute(dependencyPath)) throw Error('OpenShell native dependency module must be an absolute protected path');
  return bindDependencies(require(dependencyPath));
}

function createCompleteWorker({
  enabled = process.env.DSH_OPENSHELL_COMPLETE_WORKER === 'true',
  dependencyPath = process.env.DSH_OPENSHELL_DEPENDENCY_MODULE,
  trustedServerOrigin = process.env.DSH_OPENSHELL_TRUSTED_ORIGIN,
  deps: suppliedDependencies,
  now = Date.now,
} = {}) {
  const deps = suppliedDependencies ? bindDependencies(suppliedDependencies) : loadDependencies(enabled, dependencyPath);
  if (enabled) {
    let origin;
    try { origin = new URL(trustedServerOrigin); } catch { throw Error('OpenShell trusted origin is required'); }
    if (origin.protocol !== 'https:' || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash) throw Error('OpenShell trusted origin must be a bare HTTPS origin');
    trustedServerOrigin = origin.origin;
  }
  const sessionStates = new WeakMap();
  const userStates = new Map();

  function stateFor(session, sessionId, generation) {
    let state = sessionStates.get(session);
    if (!state) {
      state = {sessionId, generation, csrf:crypto.randomBytes(32).toString('hex'), contexts:new Map(), user:session.user};
      sessionStates.set(session,state);
      const states=userStates.get(session.user)||new Set();states.add(state);userStates.set(session.user,states);
    }
    if (state.sessionId !== sessionId || state.generation !== generation || state.user !== session.user) throw Error('SESSION_BINDING_CHANGED');
    return state;
  }

  async function readBody(req) {
    if (!String(req.headers['content-type']||'').toLowerCase().startsWith('application/json')) throw Object.assign(Error('JSON_REQUIRED'),{status:415});
    let body='',size=0;
    for await (const chunk of req) {
      size+=chunk.length;
      if(size>65536) throw Object.assign(Error('REQUEST_TOO_LARGE'),{status:413});
      body+=chunk;
    }
    try{return JSON.parse(body);}catch{throw Object.assign(Error('INVALID_JSON'),{status:400});}
  }

  async function handle(req,res,{pathname,session,sessionId,generation}) {
    if (!['/api/openshell/session','/api/openshell/complete-worker'].includes(pathname)) return false;
    if (!enabled) { json(res,404,{error:'OPENSHELL_NOT_ENABLED'}); return true; }
    if (!session || session.internet !== 'off' || !sessionId || !generation) { json(res,403,{error:'SECURE_SESSION_REQUIRED'}); return true; }
    const state=stateFor(session,sessionId,generation);
    if (pathname==='/api/openshell/session') {
      if(req.method!=='GET'){json(res,405,{error:'USE_GET'});return true;}
      json(res,200,{enabled:true,route:'complete-worker',csrfToken:state.csrf,expiresAt:now()+299000});return true;
    }
    if(req.method!=='POST'){json(res,405,{error:'USE_POST'});return true;}
    if(req.headers.origin && req.headers.origin!==trustedServerOrigin){json(res,403,{error:'UNTRUSTED_ORIGIN'});return true;}
    if(req.headers['x-dsh-openshell-csrf']!==state.csrf){json(res,403,{error:'CSRF_MISMATCH'});return true;}
    try {
      const body=await readBody(req);
      if(!exactKeys(body,['projectId','requestId','taskId']))throw Object.assign(Error('INVALID_REQUEST_SHAPE'),{status:400});
      const task=await deps.resolveTask(Object.freeze({subjectUser:session.user,generation,projectId:body.projectId,taskId:body.taskId}));
      const csrfDigest=crypto.createHash('sha256').update(state.csrf).digest('hex');
      const context=bindNativeRequest({
        session:{csrfDigest,expiresAt:now()+299000,generation,sessionId,subjectUser:session.user},
        request:{audience:'dsh-openshell-test',csrfDigest,environment:'secure',requestId:body.requestId,route:'complete-worker',serverOrigin:trustedServerOrigin},
        task,trustedServerOrigin,now:now(),
      });
      assertCurrentBinding(context,await deps.currentBinding(context));
      const receipt=await deps.dispatch(context);
      deps.cancellation.assertNoFallback(receipt);
      if(receipt.bindingId!==context.bindingId||receipt.workerUID!==context.workerUID)throw Error('DISPATCH_RECEIPT_MISMATCH');
      state.contexts.set(context.bindingId,context);
      json(res,202,{accepted:true,bindingId:context.bindingId,workerUID:context.workerUID,nativeRequired:true,unrestrictedFallback:false});
    } catch(error) { json(res,error.status||503,{error:error.code||error.message||'OPENSHELL_DISPATCH_FAILED'}); }
    return true;
  }

  async function cancelState(state,reason) {
    for(const context of [...state.contexts.values()]){
      await deps.cancellation.cancel(context,reason);
      state.contexts.delete(context.bindingId);
    }
  }
  async function cancelSession(session,reason='logout') {
    if(!enabled)return;
    const state=sessionStates.get(session);if(!state)return;
    await cancelState(state,reason);sessionStates.delete(session);
    const states=userStates.get(state.user);if(states){states.delete(state);if(!states.size)userStates.delete(state.user);}
  }
  async function cancelUser(user) {
    if(!enabled)return;
    for(const state of [...(userStates.get(user)||[])])await cancelState(state,'revocation');
    userStates.delete(user);
  }
  return Object.freeze({enabled,handle,cancelSession,cancelUser});
}

module.exports={createCompleteWorker};
