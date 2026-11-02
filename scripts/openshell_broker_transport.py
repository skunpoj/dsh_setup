"""Journal-bound native transport, injected only by an admitted server.

No credentials, namespaces, images or execution policy come from browser data.
The supervisor dependency must independently enforce exact native/Pod identity.
"""
import threading
import re
from scripts.openshell_task_binding import OpenShellBinding
from scripts.openshell_worker_execution import validate


class NativeBrokerTransport:
    def __init__(self, registry, rpc, supervisor, admitted_spec):
        if not callable(admitted_spec):raise ValueError('ADMITTED_SPEC_FACTORY_REQUIRED')
        self.registry,self.rpc,self.supervisor,self.admitted_spec=registry,rpc,supervisor,admitted_spec
        self.streams={}
        self.lock=threading.RLock()

    def _task(self, context, *, allocating=False):
        keys=OpenShellBinding.KEYS-{'workerUID'} if allocating else OpenShellBinding.KEYS
        if not isinstance(context,dict) or set(context)!=keys:raise ValueError('INVALID_TRANSPORT_CONTEXT')
        task=self.registry.get(context['taskId'])
        if task is None or task.request.get('backend')!='openshell':raise ValueError('NATIVE_TASK_NOT_FOUND')
        state=getattr(task,'openshell',None)
        if not state or any(state.get(k)!=v for k,v in context.items()):raise ValueError('STALE_TRANSPORT_BINDING')
        return task,state

    def _record_worker(self, task, state, context, response):
        native_id=response.sandbox.metadata.id
        if state.get('workerUID') not in (None,native_id):raise ValueError('NATIVE_ALLOCATION_REPLACED')
        task.openshell={**task.openshell,'workerUID':native_id};task.save()
        identity={**context,'workerUID':native_id}
        # Read-only supervisor observation binds the actual Pod before dispatch,
        # so cancellation after allocation can clean a never-started worker.
        receipt=self.supervisor.observe_exact(dict(identity))
        pod_uid=receipt.get('podUID') if isinstance(receipt,dict) else None
        if (not isinstance(pod_uid,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',pod_uid)
                or receipt!={**identity,'podUID':pod_uid}):raise ValueError('NATIVE_POD_IDENTITY_UNVERIFIED')
        if state.get('podUID') not in (None,pod_uid):raise ValueError('NATIVE_POD_REPLACED')
        task.openshell={**task.openshell,'podUID':pod_uid};task.save()
        return native_id

    def allocate(self, context, operation, expires_at):
        task,state=self._task(context,allocating=True)
        if (state.get('phase')!='allocation-reserved' or state.get('allocationOperationId')!=operation
                or state.get('expiresAt')!=expires_at):raise ValueError('UNRESERVED_NATIVE_ALLOCATION')
        response=self.rpc.create(context['bindingId'],operation,
            admitted_spec=self.admitted_spec(dict(context),expires_at),expires_at=expires_at)
        native_id=self._record_worker(task,state,context,response)
        return {**context,'workerUID':native_id,'operationId':operation}

    def lookup_allocation(self, context, operation):
        task,state=self._task(context,allocating=True)
        if state.get('allocationOperationId')!=operation:raise ValueError('ALLOCATION_OPERATION_CHANGED')
        response=self.rpc.lookup(context['bindingId'],operation)
        native_id=self._record_worker(task,state,context,response)
        return {**context,'workerUID':native_id,'operationId':operation}

    def dispatch(self, context, operation):
        with self.lock:
            task,state=self._task(context)
            if state.get('phase')!='dispatch-reserved' or state.get('operationId')!=operation or state.get('revoked') or state.get('fenced'):
                raise ValueError('UNRESERVED_OR_FENCED_DISPATCH')
            key=(context['bindingId'],operation)
            if key in self.streams:raise ValueError('NATIVE_STREAM_REPLAY')
            self.streams[key]=None
            stage=task.execution_stage
            if not stage:raise ValueError('EXECUTION_STAGE_REQUIRED')
            task.execution_stage={**stage,'executionId':operation};task.save()
            if not state.get('podUID'):raise ValueError('NATIVE_POD_IDENTITY_REQUIRED')
            envelope={**context,'podUID':state['podUID'],'operationId':operation,'expiresAt':state['expiresAt'],
                'runtime':stage['runtime'],'correlationId':stage['correlationId'],
                'prompt':task.execution_prompt,'writes':task.request['writes']}
            assigned={**context,'expiresAt':state['expiresAt'],'podUID':state['podUID']}
            validate(envelope,assigned,self.rpc.clock())
            # The supervisor must bind the envelope to the actual native worker
            # through protected assignment injection, not a user-writable file.
            receipt=self.supervisor.assign_exact(dict(assigned))
            if receipt!={**assigned,'assigned':True}:
                raise ValueError('NATIVE_ASSIGNMENT_UNVERIFIED')
            self.streams[key]=self.rpc.execute(context['bindingId'],operation,envelope)
            return {**context,'operationId':operation,'nativeRequired':True,'unrestrictedFallback':False}

    def events(self, context, operation):
        self._task(context)
        key=(context['bindingId'],operation)
        with self.lock:stream=self.streams.get(key)
        if stream is None:raise ValueError('NATIVE_STREAM_UNAVAILABLE_NO_REPLAY')
        for event in stream:
            payload=event.WhichOneof('payload')
            if payload in ('stdout','stderr'):
                yield {'type':'output','text':getattr(event,payload).data.decode('utf-8',errors='replace')}
            elif payload=='exit':
                yield {'type':'exit','exitCode':event.exit.exit_code,
                       'workerUID':context['workerUID'],'operationId':operation}
            else:raise ValueError('UNKNOWN_NATIVE_STREAM_EVENT')

    def stop_exact(self, context, operation):
        _,state=self._task(context)
        if (state.get('phase')!='stop-reserved' or state.get('stopOperationId')!=operation
                or not state.get('fenced') or not state.get('revoked') or not state.get('podUID')):
            raise ValueError('UNRESERVED_EXACT_NATIVE_STOP')
        with self.lock:
            for (binding,_),stream in self.streams.items():
                if binding==context['bindingId'] and stream is not None and hasattr(stream,'cancel'):stream.cancel()
        # No name-only RPC stop and no invented success/absence receipt.
        assigned={**context,'podUID':state['podUID']}
        receipt=self.supervisor.stop_exact(assigned,operation)
        if receipt!={**assigned,'operationId':operation,'stopped':True}:raise ValueError('EXACT_NATIVE_STOP_UNVERIFIED')
        return {'workerUID':context['workerUID'],'operationId':operation,'stopped':True}

    def verify_absent(self, context, operation):
        _,state=self._task(context)
        if state.get('phase')!='stop-reserved' or state.get('stopOperationId')!=operation or not state.get('podUID'):
            raise ValueError('UNRESERVED_EXACT_NATIVE_ABSENCE')
        assigned={**context,'podUID':state['podUID']}
        receipt=self.supervisor.verify_absent(assigned,operation)
        if receipt!={**assigned,'operationId':operation,'absent':True}:raise ValueError('EXACT_NATIVE_ABSENCE_UNVERIFIED')
        return {'workerUID':context['workerUID'],'operationId':operation,'absent':True}
