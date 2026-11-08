"""SDK-specific physical worker composition over the existing Task writer.

Requires explicit protected API/project/execution admission. No credential
discovery, package installation, qualification flag, retry or CLI substitution.
"""
import copy
import re
from scripts.a2a_worker_controller import WorkerController
from scripts.a2a_sdk_worker_pod import sdk_worker_pod
from scripts.a2a_worker_identity import annotate,template_hash
from scripts.a2a_worker_stream import WorkerStream
from scripts.a2a_sdk_transport import SDKWorkerTransport
from scripts import a2a_worker_journal as journal


class SDKWorkerController(WorkerController):
    RUNTIMES=frozenset({'sdk'})
    def __init__(self,*,generation,package_admission_sha256,**kwargs):
        if (not isinstance(generation,str) or not re.fullmatch(r'[A-Za-z0-9_.@:-]{1,128}',generation)
                or not isinstance(package_admission_sha256,str)
                or not re.fullmatch(r'[a-f0-9]{64}',package_admission_sha256)
                or package_admission_sha256=='0'*64):
            raise ValueError('EXACT_SDK_CONTROLLER_GENERATION_AND_PACKAGE_REQUIRED')
        self.generation=generation;self.package_hash=package_admission_sha256
        super().__init__(**kwargs)

    def _native(self,task,*,require_launch=False):
        expected=dict(subject=self.subject,generation=self.generation,taskId=task.id,
            sessionId=task.id,project=task.request['project'],correlationId=task.correlation_id)
        native=getattr(task,'native_sdk',None)
        if (task.authenticated_subject!=self.subject or task.request['runtime']!='sdk'
                or task.request.get('backend')!='private' or not isinstance(native,dict)
                or any(native.get(k)!=v for k,v in expected.items())
                or not re.fullmatch(r'[a-f0-9]{32}',str(native.get('launchOperationId')))):
            raise ValueError('FOREIGN_NATIVE_SDK_WORKER_TASK')
        if require_launch and (task.state!='running' or native.get('phase')!='launch-reserved'
                or native.get('guardLifecyclePending') is not True or native.get('stopOperationId')
                or native.get('postStopLifecycleFailure')):
            raise ValueError('SDK_LAUNCH_FENCED_OR_NOT_RESERVED')
        worker=getattr(task,'a2a_cli_worker',None)
        if worker is not None and worker.get('sdkBinding')!=dict(generation=self.generation,
                launchOperationId=native['launchOperationId'],packageAdmissionSha256=self.package_hash):
            raise ValueError('SDK_PHYSICAL_LAUNCH_BINDING_CHANGED')
        return expected

    def _reserve_worker(self,task,template,*,prompt_sha256):
        return journal.reserve(task,namespace=self.api.namespace,namespace_uid=self.api.namespace_uid,
            template_sha256=template_hash(template),image=self.image,sdk_binding=dict(generation=self.generation,
                launchOperationId=task.native_sdk['launchOperationId'],packageAdmissionSha256=self.package_hash),
                prompt_sha256=prompt_sha256)

    def _binding(self,task,binding):
        expected={**self._native(task),'packageAdmissionSha256':self.package_hash}
        if not isinstance(binding,dict) or binding!=expected:
            raise ValueError('EXACT_SDK_PEER_BINDING_REQUIRED')

    def _project(self,task):
        self._native(task)
        return super()._project(task)

    def _template(self,task,project):
        value=sdk_worker_pod(namespace=self.api.namespace,task_id=task.id,image=self.image,
            workspace_claim=project['claim'],project_subpath=project['subpath'],
            credential_secret=project['credentialSecret'],correlation_id=task.correlation_id,
            writes=task.request['writes'],package_admission_sha256=self.package_hash)
        value['spec']['nodeName']=self.node_name
        return value

    def prepare_sdk(self,task,*,binding):
        self._binding(task,binding);self._native(task,require_launch=True);self._execution(task)
        context=dict(subject=self.subject,stageId=task.id,correlationId=task.correlation_id,
                     project=task.request['project'],runtime='sdk')
        with task.persistence_lock:
            if getattr(task,'a2a_cli_context',None) not in (None,context):
                raise ValueError('SDK_PHYSICAL_CONTEXT_ALREADY_BOUND')
            task.a2a_cli_context=context;task.save()
        project=self._project(task)
        return self._create_worker(task,project)

    def make_transport(self,task,*,binding,stream_factory=WorkerStream):
        """Inert pipe object for an already created worker; start consumes IO."""
        self._binding(task,binding)
        record=copy.deepcopy(task.a2a_cli_worker)
        if not record or record['phase']!='bound' or not record['podUID']:
            raise ValueError('BOUND_SDK_WORKER_REQUIRED_BEFORE_TRANSPORT')
        expected=annotate(self._template(task,self._project(task)),namespace_uid=record['namespaceUID'],
                          operation_id=record['createOperationId'])
        def before_start():
            self._native(task,require_launch=True);self._execution(task,model=True)
            if self.observe(task,require_running=True)['resourceAbsent']:
                raise ValueError('SDK_WORKER_ABSENT_NO_DISPATCH')
            journal.reserve_dispatch(task,pod_uid=record['podUID'])
        def before_attach():
            self._native(task,require_launch=True);self._execution(task,model=True)
            journal.reserve_attach(task,pod_uid=record['podUID'])
        def before_cancel(operation_id):
            self._binding(task,binding)
            journal.reserve_sdk_stop_frame(task,pod_uid=record['podUID'],operation_id=operation_id)
        stream=stream_factory(api=self.api,expected_pod=expected,pod_uid=record['podUID'],before_attach=before_attach)
        admission=self._execution(task)
        transport=SDKWorkerTransport(stream=stream,context={**task.a2a_cli_context,'scopeUid':record['podUID']},
            timeout_seconds=min(120,admission['expiresAt']-self.clock()),before_start=before_start,before_cancel=before_cancel)
        with self.streams_lock:
            if task.id in self.streams:raise ValueError('SDK_TRANSPORT_ALREADY_EXISTS_NO_REATTACH')
            self.streams[task.id]=stream
        return transport

    def prepare_cli(self,*_,**__):raise ValueError('SDK_OFFICIAL_CONTROL_ONLY')
    def reserve_cli_dispatch(self,*_,**__):raise ValueError('SDK_OFFICIAL_CONTROL_ONLY')
    def open_cli_stream(self,*_,**__):raise ValueError('SDK_OFFICIAL_CONTROL_ONLY')
    def send_cancel_once(self,*_,**__):raise ValueError('SDK_NATIVE_STOP_RESERVATION_REQUIRED')

    def observe_cancel(self,task,*,operation_id):
        self._native(task)
        native=task.native_sdk;worker=task.a2a_cli_worker
        if native.get('stopOperationId')!=operation_id or worker.get('stopFrameOperationId')!=operation_id:
            raise ValueError('EXACT_NATIVE_SDK_STOP_RECEIPT_REQUIRED')
        receipt=self.observe_terminal(task)
        if receipt.get('cancelled') is not True or receipt.get('operationId')!=operation_id:
            raise ValueError('SDK_PHYSICAL_STOP_OPERATION_UNVERIFIED')
        return receipt
