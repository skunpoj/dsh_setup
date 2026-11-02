'use strict';

const assert=require('node:assert/strict');
const {Readable}=require('stream');
const {createCompleteWorker}=require('../scripts/openshell-native/complete_worker.cjs');

class Response {
  writeHead(status,headers){this.status=status;this.headers=headers;}
  end(body=''){this.body=body;this.writableEnded=true;}
  value(){return this.body?JSON.parse(this.body):null;}
}
function request(method,pathname,headers={},body=''){
  const req=Readable.from(body?[Buffer.from(body)]:[]);req.method=method;req.url=pathname;req.headers=headers;return req;
}
function dependencies(order){
  const task={bindingId:'bind1',ownerUser:'alice',projectId:'project1',taskId:'task1',workerGeneration:'g'.repeat(64),workerUID:'worker1'};
  const receipt=(a,name,value={})=>{order.push(name);return{operationId:a.operationId,...value};};
  return {
    resolveTask:async()=>task,
    currentBinding:async()=>({ownerUser:'alice',workerGeneration:'g'.repeat(64),bindingId:'bind1',workerUID:'worker1'}),
    dispatch:async()=>({bindingId:'bind1',workerUID:'worker1',nativeRequired:true,unrestrictedFallback:false}),
    cancellation:{
      journal:{active:async()=>[task],fence:async a=>receipt(a,'journal-fence',{fenced:true}),finish:async a=>receipt(a,'journal-finish',{finished:true})},
      broker:{revoke:async a=>receipt(a,'broker-revoke',{bindingId:'bind1',revoked:true}),fence:async a=>receipt(a,'broker-fence',{fenced:true})},
      transport:{fence:async a=>receipt(a,'transport-fence',{fenced:true}),stop:async a=>receipt(a,'workload-stop',{bindingId:'bind1',workerUID:'worker1',stopped:true})},
      supervisor:{stopExact:async a=>receipt(a,'supervisor-stop',{bindingId:'bind1',workerUID:'worker1',stopped:true}),verifyAbsent:async a=>receipt(a,'absence',{workerUID:'worker1',absent:true})},
    },
  };
}

async function main(){
  const disabled=createCompleteWorker({enabled:false});
  const disabledRes=new Response();
  assert.equal(await disabled.handle(request('GET','/api/openshell/session'),disabledRes,{pathname:'/api/openshell/session'}),true);
  assert.equal(disabledRes.status,404);

  const order=[],clock=()=>100000;
  const integration=createCompleteWorker({enabled:true, trustedServerOrigin:'https://dsh.example.test',deps:dependencies(order),now:clock});
  const session={user:'alice',internet:'off',created:1},sessionId='s'.repeat(48),generation='g'.repeat(64);
  const sessionRes=new Response();
  await integration.handle(request('GET','/api/openshell/session'),sessionRes,{pathname:'/api/openshell/session',session,sessionId,generation});
  assert.equal(sessionRes.status,200);const token=sessionRes.value().csrfToken;assert.match(token,/^[a-f0-9]{64}$/);

  const dispatchRes=new Response();
  await integration.handle(request('POST','/api/openshell/complete-worker',{'content-type':'application/json','origin':'https://dsh.example.test','x-dsh-openshell-csrf':token},JSON.stringify({projectId:'project1',requestId:'request1',taskId:'task1'})),dispatchRes,{pathname:'/api/openshell/complete-worker',session,sessionId,generation});
  assert.equal(dispatchRes.status,202);assert.deepEqual(dispatchRes.value(),{accepted:true,bindingId:'bind1',workerUID:'worker1',nativeRequired:true,unrestrictedFallback:false});

  await integration.cancelSession(session,'logout');
  assert.deepEqual(order,['journal-fence','broker-revoke','broker-fence','transport-fence','workload-stop','supervisor-stop','absence','journal-finish']);

  const internetRes=new Response();
  await integration.handle(request('GET','/api/openshell/session'),internetRes,{pathname:'/api/openshell/session',session:{user:'alice',internet:'on'},sessionId,generation});
  assert.equal(internetRes.status,403);

  const wrongOrigin=new Response();
  await integration.handle(request('POST','/api/openshell/complete-worker',{'content-type':'application/json','origin':'https://evil.invalid','x-dsh-openshell-csrf':'x'.repeat(64)},'{}'),wrongOrigin,{pathname:'/api/openshell/complete-worker',session:{user:'alice',internet:'off'},sessionId:'t'.repeat(48),generation});
  assert.equal(wrongOrigin.status,403);
  console.log(JSON.stringify({passed:8,failed:0,cancellationOrder:order}));
}
main().catch(error=>{console.error(error);process.exitCode=1;});
