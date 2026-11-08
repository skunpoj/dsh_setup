"""Task-owned physical CLI worker creation, observation and dispatch reservation.

Uses the actual scoped worker API. Stream attach/stop/reconcile/retirement and
the SDK control transport are separate mandatory components. This class has no
qualified flag and cannot serve as an accepted CLI supervisor by itself.
"""
import copy
import re
import time
import hashlib
import json
import threading
import base64
from scripts.agent_runtime_commands import command_for
from scripts.a2a_private_worker_pod import worker_pod
from scripts.a2a_worker_identity import template_hash,annotate,verify_pod,verify_terminal_worker
from scripts import a2a_worker_journal as journal
from scripts.a2a_worker_stream import WorkerStream


class WorkerController:
    RUNTIMES=frozenset({'claude','deepagents'})
    def __init__(self, *, api, subject, image, source_commit, node_name,
                 project_admission, execution_admission, clock=time.time):
        if not re.fullmatch(r'dsh-a2a-[a-z0-9][a-z0-9-]{0,54}',str(api.namespace)):
            raise ValueError('A2A_OWNED_TEST_NAMESPACE_REQUIRED')
        if not isinstance(subject,str) or not subject or len(subject)>128:
            raise ValueError('FIXED_WORKER_SUBJECT_REQUIRED')
        if not isinstance(source_commit,str) or not re.fullmatch(r'[a-f0-9]{40}',source_commit):
            raise ValueError('PINNED_WORKER_SOURCE_REQUIRED')
        if not isinstance(node_name,str) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,252}',node_name):
            raise ValueError('ADMITTED_PRIVATE_WORKER_NODE_REQUIRED')
        if not callable(project_admission) or not callable(execution_admission):
            raise ValueError('PROTECTED_WORKER_ADMISSION_REQUIRED')
        self.api,self.subject,self.image=api,subject,image
        self.source_commit,self.node_name=source_commit,node_name
        self.project_admission,self.execution_admission,self.clock=project_admission,execution_admission,clock
        self.streams={};self.dispatch_completion={};self.streams_lock=threading.Lock()

    def _prompt_sha(self,task,*,require_raw=False):
        worker=getattr(task,'a2a_cli_worker',None)
        frozen=worker.get('promptSha256') if isinstance(worker,dict) else None
        prompt=task.request.get('prompt')
        if isinstance(prompt,str):
            digest=hashlib.sha256(prompt.encode()).hexdigest()
            if frozen is not None and frozen!=digest:raise ValueError('WORKER_PROMPT_BINDING_CHANGED')
            return digest
        if require_raw or not isinstance(frozen,str) or not re.fullmatch(r'[a-f0-9]{64}',frozen):
            raise ValueError('RAW_PROMPT_REQUIRED_FOR_NEW_WORKER_DISPATCH')
        return frozen  # Recovery/cleanup only; never a replacement model prompt.

    def _execution(self, task, *, model=False):
        prompt_sha=self._prompt_sha(task,require_raw=model or getattr(task,'a2a_cli_worker',None) is None)
        value=self.execution_admission(self.subject,task.id,task.correlation_id,
            task.request['project'],task.request['runtime'],task.request['writes'],prompt_sha)
        expected={'subject':self.subject,'namespace':self.api.namespace,
            'namespaceUID':self.api.namespace_uid,'image':self.image,
            'sourceCommit':self.source_commit,'nodeName':self.node_name,'mode':'private-test',
            'taskId':task.id,'correlationId':task.correlation_id,
            'project':task.request['project'],'runtime':task.request['runtime'],'writes':task.request['writes'],
            'promptSha256':prompt_sha}
        if (not isinstance(value,dict) or set(value)!=set(expected)|{'expiresAt','modelStartsAllowed'}
                or any(value.get(k)!=v for k,v in expected.items())
                or type(value['expiresAt']) not in (int,float)
                or not 0<value['expiresAt']-self.clock()<=300
                or type(value['modelStartsAllowed']) is not int
                or value['modelStartsAllowed'] not in {0,1}
                or (model and value['modelStartsAllowed']!=1)):
            raise ValueError('FRESH_PRIVATE_WORKER_EXECUTION_ADMISSION_REQUIRED')
        return value

    def _project(self,task):
        context=getattr(task,'a2a_cli_context',None)
        if (task.authenticated_subject!=self.subject or not isinstance(context,dict)
                or context!=dict(subject=self.subject,stageId=task.id,
                    correlationId=task.correlation_id,project=task.request['project'],runtime=task.request['runtime'])
                or task.request['runtime'] not in self.RUNTIMES):
            raise ValueError('FOREIGN_PRIVATE_WORKER_TASK')
        value=self.project_admission(self.subject,task.request['project'])
        if (not isinstance(value,dict) or set(value)!={'claim','subpath','writes','brokerPath','credentialSecret'}
                or type(value['writes']) is not bool or type(task.request['writes']) is not bool
                or task.request['writes'] and not value['writes']):
            raise ValueError('PRIVATE_PROJECT_OWNERSHIP_OR_WRITE_ADMISSION_REQUIRED')
        return value

    def _template(self,task,project):
        value=worker_pod(namespace=self.api.namespace,task_id=task.id,image=self.image,
            workspace_claim=project['claim'],project_subpath=project['subpath'],
            credential_secret=project['credentialSecret'],correlation_id=task.correlation_id,
            writes=task.request['writes'])
        value['spec']['nodeName']=self.node_name
        return value

    def prepare_cli(self,task,command,broker_project):
        self._execution(task)
        project=self._project(task)
        if (str(broker_project)!=project['brokerPath'] or command!=command_for(task.request['runtime'],
                task.request['prompt'],task.request['writes'],broker_project,task.id)):
            raise ValueError('PRIVATE_WORKER_COMMAND_OR_PROJECT_CHANGED')
        return self._create_worker(task,project)

    def _create_worker(self,task,project):
        template=self._template(task,project)
        # Classify an existing name, never overwrite/adopt it as a new create.
        if self.api.read_pod(template['metadata']['name']) is not None:
            raise ValueError('WORKER_NAME_ALREADY_PRESENT_NO_CREATE')
        admission=self._execution(task)
        record=self._reserve_worker(task,template,prompt_sha256=admission['promptSha256'])
        expected=annotate(template,namespace_uid=record['namespaceUID'],operation_id=record['createOperationId'])
        created=self.api.create_pod_once(expected)  # Exactly one call after durable reservation.
        identity=verify_pod(created,expected)
        return journal.bind_created(task,operation_id=record['createOperationId'],pod_uid=identity['podUID'])

    def _reserve_worker(self,task,template,*,prompt_sha256):
        return journal.reserve(task,namespace=self.api.namespace,namespace_uid=self.api.namespace_uid,
            template_sha256=template_hash(template),image=self.image,prompt_sha256=prompt_sha256)

    def observe(self,task, *, require_running=False):
        # Read-only recovery remains possible after the execution lease expires.
        # It never resubmits or reattaches a process/model operation.
        project=self._project(task)
        record=copy.deepcopy(getattr(task,'a2a_cli_worker',None))
        if (not record or record['namespace']!=self.api.namespace
                or record['namespaceUID']!=self.api.namespace_uid or record['image']!=self.image):
            raise ValueError('FOREIGN_OR_MISSING_WORKER_RESERVATION')
        template=self._template(task,project)
        if template_hash(template)!=record['templateSha256']:
            raise ValueError('RECOVERED_WORKER_PROFILE_CHANGED')
        expected=annotate(template,namespace_uid=record['namespaceUID'],operation_id=record['createOperationId'])
        actual=self.api.read_pod(record['podName'])
        if actual is None:
            return {'resourceAbsent':True,'processExitVerified':False,'podUID':record['podUID']}
        identity=verify_pod(actual,expected,pod_uid=record['podUID'],require_running=require_running)
        if record['podUID'] is None and record['phase']=='create-reserved':
            journal.bind_created(task,operation_id=record['createOperationId'],pod_uid=identity['podUID'])
        return {'resourceAbsent':False,'processExitVerified':False,**identity,'pod':actual}

    def observe_terminal(self,task,*,stream_receipt=None):
        """Recover physical exit from the exact Pod, without reattaching.

        This does not retire the worker or establish guard/LiteLLM reconciliation.
        A lost answer remains unavailable even when descendant exit is proven.
        """
        observation=self.observe(task)
        if observation['resourceAbsent']:
            raise ValueError('ABSENT_WORKER_IS_NOT_TERMINAL_EVIDENCE')
        record=copy.deepcopy(task.a2a_cli_worker)
        if record['phase']!='dispatch-reserved' or not record.get('attachOperationId'):
            raise ValueError('DISPATCHED_ATTACHED_WORKER_REQUIRED')
        expected=annotate(self._template(task,self._project(task)),namespace_uid=record['namespaceUID'],
                          operation_id=record['createOperationId'])
        return verify_terminal_worker(observation['pod'],expected,pod_uid=record['podUID'],
            context=task.a2a_cli_context,stream_receipt=stream_receipt)

    def retain_terminal(self,task,*,stream_receipt=None):
        verified=self.observe_terminal(task,stream_receipt=stream_receipt)
        # Reuse the actual independently validated termination message. The
        # journal accepts metadata only, never the stream's raw output body.
        from scripts.a2a_worker_receipt import FIELDS
        projection={key:value for key,value in verified.items()
                    if key in FIELDS|{'kind','stopped','processExitVerified','descendantAbsenceVerified',
                        'pidNamespaceInode','exitCode','outputSha256','cancelled','operationId','neverStarted'}}
        return journal.retain_terminal_projection(task,pod_uid=verified['podUID'],projection=projection)

    def recover_terminal(self,task):
        """Reconcile saved bytes with current exact Pod; never restart work."""
        saved=journal.read_terminal_projection(task)
        current=self.observe_terminal(task)
        if any(current.get(key)!=value for key,value in saved.items()):
            raise ValueError('SAVED_AND_OBSERVED_TERMINAL_EVIDENCE_CHANGED')
        return current

    def drain_guard(self,task,*,stream_factory=WorkerStream):
        """One metadata-only guard attach after durable physical worker stop.

        No model start, reconnect, provider-stop or retirement claim. A lost
        reply leaves the consumed guard operation unresolved, never resent.
        """
        self._execution(task)
        self.recover_terminal(task)
        record=copy.deepcopy(task.a2a_cli_worker)
        expected=annotate(self._template(task,self._project(task)),namespace_uid=record['namespaceUID'],
                          operation_id=record['createOperationId'])
        reserved={}
        def before_attach():
            self._execution(task)
            self.recover_terminal(task)
            reserved['operation']=journal.reserve_guard_attach(task,pod_uid=record['podUID'])
        stream=stream_factory(api=self.api,expected_pod=expected,pod_uid=record['podUID'],
            before_attach=before_attach,container='model-guard',terminal_context=task.a2a_cli_context)
        key=task.id+':guard'
        with self.streams_lock:
            if key in self.streams:raise ValueError('GUARD_STREAM_ALREADY_EXISTS_NO_REATTACH')
            self.streams[key]=stream
        try:
            stream.start()
            request=dict(kind='fence-and-snapshot',taskId=task.id,correlationId=task.correlation_id,
                         podUID=record['podUID'],operationId=reserved['operation'])
            stream.send_line(json.dumps(request,separators=(',',':')))
            raw=stream.receive_line(timeout=10)
            from scripts.official_sdk_package_admission import unique_json
            receipt=unique_json(raw.encode())
            fields={'kind','taskId','correlationId','podUID','operationId','localInflightDrained',
                    'providerExecutionStoppedVerified','ledgerSha256','ledgerBase64'}
            if (not isinstance(receipt,dict) or set(receipt)!=fields
                    or receipt['kind']!='DSH_GUARD_LOCAL_DRAIN_V1'
                    or any(receipt.get(k)!=request[k] for k in ('taskId','correlationId','podUID','operationId'))
                    or receipt['localInflightDrained'] is not True
                    or receipt['providerExecutionStoppedVerified'] is not False
                    or not isinstance(receipt['ledgerBase64'],str) or len(receipt['ledgerBase64'])>87384):
                raise ValueError('GUARD_DRAIN_RECEIPT_BINDING_UNVERIFIED')
            ledger=base64.b64decode(receipt['ledgerBase64'],validate=True)
            if hashlib.sha256(ledger).hexdigest()!=receipt['ledgerSha256']:
                raise ValueError('GUARD_DRAIN_LEDGER_HASH_MISMATCH')
            rows=journal.validate_guard_ledger(task,ledger)
            if not any(row['event']=='task-fenced' and row['operation_id']==reserved['operation'] for row in rows):
                raise ValueError('GUARD_DRAIN_FENCE_OPERATION_UNVERIFIED')
            journal.retain_guard_ledger(task,pod_uid=record['podUID'],ledger_bytes=ledger)
            return {'localInflightDrained':True,'providerExecutionStoppedVerified':False,
                    'ledgerSha256':receipt['ledgerSha256'],'operationId':reserved['operation']}
        finally:stream.close()

    def observe_drained_guard(self,task):
        """Require captured ledger bytes AND actual clean guard process exit."""
        rows=journal.read_guard_ledger(task)
        terminal=self.recover_terminal(task)
        observation=self.observe(task)
        if observation['resourceAbsent']:raise ValueError('ABSENCE_IS_NOT_CLEAN_GUARD_EXIT')
        statuses=observation['pod'].get('status',{}).get('containerStatuses',[])
        guard=next(value for value in statuses if value.get('name')=='model-guard')
        exited=guard.get('state',{}).get('terminated')
        if (not terminal['guardStopped'] or not isinstance(exited,dict)
                or type(exited.get('exitCode')) is not int or exited['exitCode']!=0
                or not isinstance(exited.get('finishedAt'),str) or not exited['finishedAt']):
            raise ValueError('CLEAN_GUARD_PROCESS_EXIT_UNVERIFIED')
        # Reverify the second API snapshot, including immutable image/generation.
        record=task.a2a_cli_worker
        expected=annotate(self._template(task,self._project(task)),namespace_uid=record['namespaceUID'],
                          operation_id=record['createOperationId'])
        verify_terminal_worker(observation['pod'],expected,pod_uid=record['podUID'],context=task.a2a_cli_context)
        return {'localGuardExitVerified':True,'ledgerSha256':record['guardLedgerSha256'],
                'reservedUpstreamStarts':sum(row['event']=='upstream-start-reserved' for row in rows),
                'providerExecutionStoppedVerified':False,'workerRetired':False}

    def send_cancel_once(self,task,*,operation_id):
        """Send the already broker-reserved stop on the existing stream only."""
        self._execution(task)
        self._project(task)
        observation=self.observe(task,require_running=True)
        if observation['resourceAbsent']:raise ValueError('ABSENCE_IS_NOT_A_STOP_RECEIPT')
        with self.streams_lock:
            stream=self.streams.get(task.id);dispatch=self.dispatch_completion.get(task.id)
        if stream is None or dispatch is None:
            raise ValueError('EXISTING_WORKER_STREAM_REQUIRED_NO_REATTACH')
        journal.reserve_stop_frame(task,pod_uid=observation['podUID'],operation_id=operation_id)
        if not dispatch['done'].wait(5) or not dispatch['delivered']:
            stream.close()  # Abort uncertain initial delivery; never resend it.
            raise ValueError('INITIAL_DELIVERY_UNCERTAIN_STOP_NOT_VERIFIED')
        request=dict(kind='cancel',context={**task.a2a_cli_context,'scopeUid':observation['podUID']},
                     operationId=operation_id)
        stream.send_line(json.dumps(request,separators=(',',':')))
        return {'operationId':operation_id,'stopFrameDelivered':True,'processExitVerified':False}

    def observe_cancel(self,task,*,operation_id):
        cancel=getattr(task,'a2a_cli_cancel',None)
        record=getattr(task,'a2a_cli_worker',None)
        if (not isinstance(cancel,dict) or not isinstance(record,dict)
                or cancel.get('operationId')!=operation_id or record.get('stopFrameOperationId')!=operation_id):
            raise ValueError('EXACT_RESERVED_STOP_RECEIPT_REQUIRED')
        receipt=self.observe_terminal(task)
        if receipt.get('cancelled') is not True or receipt.get('operationId')!=operation_id:
            raise ValueError('PHYSICAL_CANCEL_OPERATION_UNVERIFIED')
        return receipt

    def reserve_cli_dispatch(self,task):
        self._execution(task,model=True)
        self._project(task)
        observation=self.observe(task,require_running=True)
        if observation['resourceAbsent']:raise ValueError('WORKER_ABSENT_NO_DISPATCH')
        admission=self._execution(task,model=True)
        journal.reserve_dispatch(task,pod_uid=observation['podUID'])
        command=command_for(task.request['runtime'],task.request['prompt'],task.request['writes'],'/workspace',task.id)
        separator=command.index('--')
        command[separator:separator]=['--external-guard-port','4001']
        # Raw prompt travels in the private stream only, never the Pod/Task
        # manifest or journal. The caller MUST NOT log this request object.
        remaining=admission['expiresAt']-self.clock()
        if remaining<=0:raise ValueError('WORKER_ADMISSION_EXPIRED_BEFORE_STREAM_DISPATCH')
        return dict(context={**task.a2a_cli_context,'scopeUid':observation['podUID']},command=command,
            cwd='/workspace',uid=10001,gid=10001,environment={
                'PATH':'/opt/dsh/deepagents/bin:/usr/local/bin:/usr/bin:/bin',
                'HOME':'/home/dsh','LANG':'C.UTF-8','DSH_CORRELATION_ID':task.correlation_id},
            timeoutSeconds=min(120,remaining))

    def open_cli_stream(self,task,*,stream_factory=WorkerStream):
        request=self.reserve_cli_dispatch(task)
        record=copy.deepcopy(task.a2a_cli_worker)
        expected=annotate(self._template(task,self._project(task)),namespace_uid=record['namespaceUID'],
                          operation_id=record['createOperationId'])
        def before_attach():
            self._execution(task,model=True)
            journal.reserve_attach(task,pod_uid=record['podUID'])
        stream=stream_factory(api=self.api,expected_pod=expected,pod_uid=record['podUID'],
                              before_attach=before_attach)
        with self.streams_lock:
            if task.id in self.streams:raise ValueError('WORKER_STREAM_HANDLE_ALREADY_EXISTS')
            self.streams[task.id]=stream  # Keep the same handle on observation timeouts.
            dispatch={'done':threading.Event(),'delivered':False}
            self.dispatch_completion[task.id]=dispatch
        try:
            stream.start()
            self._execution(task,model=True)
            with task.persistence_lock:
                if task.state!='running':raise ValueError('WORKER_FENCED_BEFORE_INITIAL_FRAME')
            # No potentially blocked pipe/network IO under the Task lock:
            # cancellation must be able to persist its fence immediately.
            stream.send_line(json.dumps(request,separators=(',',':'),ensure_ascii=False))
            dispatch['delivered']=True
            return stream
        except BaseException:
            stream.close()
            raise
        finally:dispatch['done'].set()
