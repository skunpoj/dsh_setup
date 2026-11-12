"""Physical SDK lifecycle composition for the existing protected Task writer.

No qualification flag, admission factory, credentials, deployment, new writer,
retry or local subprocess fallback. The protected owner must supply fresh
scope admission and the already scoped controller outside the user runtime.
"""
import copy
import threading
import time
from scripts.official_sdk_control_peer import COMMAND
from scripts.a2a_worker_stream import WorkerStream
from scripts.a2a_private_worker_pod import worker_pod_name


class _DeferredTransport:
    """SDKControlPeer is constructed BEFORE durable launch; remain inert."""
    def __init__(self):
        self.lock=threading.Lock();self.actual=None;self.closed=False

    def bind(self,transport):
        with self.lock:
            if self.closed or self.actual is not None:
                raise ValueError('SDK_DEFERRED_TRANSPORT_FENCED_OR_BOUND')
            self.actual=transport

    def _get(self):
        with self.lock:
            if self.closed or self.actual is None:
                raise ValueError('SDK_PHYSICAL_TRANSPORT_NOT_LAUNCH_BOUND')
            return self.actual

    def start(self,bootstrap):return self._get().start(bootstrap)
    def send(self,frame):return self._get().send(frame)
    def receive(self):return self._get().receive()
    def cancel_once(self,operation):return self._get().cancel_once(operation)
    def close(self):
        with self.lock:
            self.closed=True;actual=self.actual
        if actual is not None:actual.close()


class SDKControllerLifecycle:
    def __init__(self,*,controller,task_lookup,stream_factory=WorkerStream,observation_timeout=2):
        if not callable(task_lookup) or not callable(stream_factory):
            raise ValueError('EXISTING_TASK_LOOKUP_AND_PRIVATE_STREAM_REQUIRED')
        if type(observation_timeout) not in (int,float) or not 0<observation_timeout<=2:
            raise ValueError('BOUNDED_SDK_STOP_OBSERVATION_REQUIRED')
        self.controller=controller;self.task_lookup=task_lookup
        self.stream_factory=stream_factory;self.lock=threading.Lock();self.handles={}
        self.observation_timeout=observation_timeout

    def _task(self,binding):
        if not isinstance(binding,dict):raise ValueError('EXACT_SDK_BINDING_REQUIRED')
        task=self.task_lookup(binding.get('taskId'))
        if task is None:raise ValueError('EXISTING_SDK_TASK_REQUIRED')
        expected=dict(subject=self.controller.subject,generation=self.controller.generation,
            taskId=task.id,sessionId=task.id,project=task.request['project'],
            correlationId=task.correlation_id,packageAdmissionSha256=self.controller.package_hash)
        if binding!=expected or task.authenticated_subject!=self.controller.subject:
            raise ValueError('FOREIGN_SDK_LIFECYCLE_BINDING')
        return task

    def control_transport(self,*,binding,command):
        task=self._task(binding)
        if command!=COMMAND:raise ValueError('FIXED_OFFICIAL_SDK_CONTROL_COMMAND_REQUIRED')
        with self.lock:
            if task.id in self.handles:raise ValueError('SDK_CONTROL_HANDLE_EXISTS_NO_REPLACEMENT')
            transport=_DeferredTransport()
            self.handles[task.id]=dict(binding=copy.deepcopy(binding),transport=transport,startConsumed=False)
        return transport  # No controller/API call, Task write or process start.

    def _handle(self,harness):
        task=self._task(harness.binding)
        with self.lock:record=self.handles.get(task.id)
        if (record is None or record['binding']!=harness.binding
                or harness.transport is not record['transport']):
            raise ValueError('EXACT_EXISTING_SDK_CONTROL_HANDLE_REQUIRED')
        return task,record

    def _identity(self,task,observation):
        return dict(namespace=self.controller.api.namespace,namespaceUID=self.controller.api.namespace_uid,
            podUID=observation['podUID'],image=self.controller.image,
            templateSha256=observation['templateSha256'],
            launchOperationId=task.native_sdk['launchOperationId'])

    def start(self,harness,context):
        task,record=self._handle(harness)
        expected={k:v for k,v in record['binding'].items() if k!='packageAdmissionSha256'}
        with task.persistence_lock:
            self.controller._native(task,require_launch=True)
            if context!={**expected,'operationId':task.native_sdk['launchOperationId']}:
                raise ValueError('EXACT_DURABLE_SDK_LAUNCH_REQUIRED')
        with self.lock:
            if record['startConsumed']:raise ValueError('SDK_PHYSICAL_START_CONSUMED_NO_REPLAY')
            with record['transport'].lock:
                if record['transport'].closed:raise ValueError('SDK_CONTROL_CLOSED_BEFORE_LAUNCH')
            record['startConsumed']=True
        self.controller.prepare_sdk(task,binding=record['binding'])
        actual=self.controller.make_transport(task,binding=record['binding'],stream_factory=self.stream_factory)
        try:record['transport'].bind(actual)
        except BaseException:
            actual.close()  # Local close is NOT remote stop proof.
            raise
        harness.start()
        observation=self.controller.observe(task,require_running=True)
        if observation['resourceAbsent']:raise ValueError('SDK_STARTED_WORKER_ABSENT')
        return {**context,'started':True,'runtimeIdentity':self._identity(task,observation)}

    def _stop_context(self,task,context):
        self.controller._native(task)
        native=task.native_sdk
        expected={k:native[k] for k in ('subject','generation','taskId','sessionId','project','correlationId')}
        expected.update(operationId=native.get('stopOperationId'),launchOperationId=native['launchOperationId'])
        if not expected['operationId'] or context!=expected:
            raise ValueError('EXACT_DURABLE_SDK_STOP_REQUIRED')

    def _never_started(self,task,record):
        """True only when NO physical start was ever attempted for this launch: the start was not consumed and no worker reservation exists.

        start() consumes the launch under self.lock BEFORE any create call, so both facts together prove that no Pod create was submitted.
        A refused launch (for example a zero model allowance in a strict-cancel case) lands here, not in the worker-observation path below."""
        with self.lock:
            if record['startConsumed']:return False
        return not getattr(task,'a2a_cli_worker',None)

    def _fence_never_started(self,task,record,harness,context):
        # Absence is READ, not assumed: the exact worker Pod name derived from the bound template must not exist.
        name=worker_pod_name(task.id)      # same function the Pod template uses; the template itself needs a2a context that start() creates
        # STRICT (Option B): a read that cannot be made propagates, the stop stays uncertain and stopFailureCode names why. Never a never-started receipt without the observation.
        present=self.controller.api.read_pod(name) is not None
        if present:raise ValueError('SDK_NEVER_STARTED_BUT_WORKER_POD_PRESENT')
        with self.lock:
            if record['startConsumed']:raise ValueError('SDK_NEVER_STARTED_RACED_WITH_START')
            record['startConsumed']=True          # a later start() is refused (NO_REPLAY) and the closed transport cannot bind
        record['transport'].close()
        harness.close()
        return {**context,'stopped':True,'processExitVerified':True,'descendantAbsenceVerified':True,
            'launchFenced':True,'neverStarted':True,'runtimeIdentity':None}

    def stop_and_verify(self,harness,context):
        task,record=self._handle(harness)
        with task.persistence_lock:self._stop_context(task,context)
        if self._never_started(task,record):return self._fence_never_started(task,record,harness,context)
        # No reattach or start if launch is still uncertain. A real saved stop
        # reservation and the original transport are required for this action.
        record['transport'].cancel_once(context['operationId'])
        deadline=time.monotonic()+self.observation_timeout
        while True:
            try:
                proof=self.controller.observe_cancel(task,operation_id=context['operationId'])
                break
            except ValueError as error:
                # Only terminal-status propagation may be observed again.
                # Authentication, identity, API and receipt faults never retry;
                # the cancel frame is outside this loop and sent exactly once.
                if str(error)!='WORKER_INIT_EXIT_UNVERIFIED' or time.monotonic()>=deadline:raise
                time.sleep(.025)
        self.controller.retain_terminal(task)
        harness.close()
        reader=getattr(harness,'reader',None)
        if reader is not None:
            reader.join(timeout=1)
            if reader.is_alive():raise ValueError('SDK_CONTROL_READER_EXIT_UNVERIFIED')
        return {**context,'stopped':proof['stopped'],'processExitVerified':proof['processExitVerified'],
            'descendantAbsenceVerified':proof['descendantAbsenceVerified'],'launchFenced':True,
            'runtimeIdentity':self._identity(task,proof)}

    def inspect_exit(self,context):
        # Recovery observes the exact Pod and retains its late stop metadata
        # in the existing Task journal if needed. No new transport/stop/model.
        task=self.task_lookup(context.get('taskId'))
        if task is None:raise ValueError('EXISTING_SDK_TASK_REQUIRED')
        binding={k:task.native_sdk[k] for k in
            ('subject','generation','taskId','sessionId','project','correlationId')}
        binding['packageAdmissionSha256']=self.controller.package_hash
        self._task(binding);self.controller._native(task)
        expected={k:v for k,v in binding.items() if k!='packageAdmissionSha256'}
        expected.update(launchOperationId=task.native_sdk['launchOperationId'],
                        runtimeIdentity=task.native_sdk.get('runtimeIdentity'))
        if context!=expected or not task.native_sdk.get('stopOperationId'):
            raise ValueError('EXACT_SDK_RECOVERY_BINDING_REQUIRED')
        stop_id=task.native_sdk['stopOperationId']
        if (not isinstance(task.a2a_cli_worker,dict)
                or task.a2a_cli_worker.get('stopFrameOperationId')!=stop_id):
            raise ValueError('SDK_RECOVERY_STOP_OPERATION_CHANGED')
        proof=self.controller.observe_cancel(task,operation_id=stop_id)
        identity=self._identity(task,proof)
        if identity!=context['runtimeIdentity']:
            raise ValueError('SDK_RECOVERED_PHYSICAL_IDENTITY_CHANGED')
        with task.persistence_lock:
            if task.native_sdk['stopOperationId']!=stop_id:
                raise ValueError('SDK_RECOVERY_STOP_OPERATION_CHANGED')
            pending=task.a2a_cli_worker.get('terminalReceiptSha256') is None
        if pending:self.controller.retain_terminal(task)
        proof=self.controller.recover_terminal(task)
        if (proof.get('cancelled') is not True or proof.get('operationId')!=stop_id
                or task.native_sdk['stopOperationId']!=stop_id):
            raise ValueError('SDK_RECOVERY_STOP_OPERATION_CHANGED')
        return {**context,'operationId':stop_id,
            'stopped':proof['stopped'],'processExitVerified':proof['processExitVerified'],
            'descendantAbsenceVerified':proof['descendantAbsenceVerified'],'launchFenced':True}
