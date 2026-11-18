"""No-retry banking Kubernetes backend. All identity/API/auth inputs injected.

No credential discovery, API call, attach, provider call or resource creation at
import. open_guard consumes its caller's durable reservation before POST. A
partial/unknown creation is never retried; original WAL and objects retained.
"""
import copy
import os
from pathlib import Path
import re
import time
from types import SimpleNamespace
from contextlib import contextmanager
from scripts.banking_sdk_scope_factory import canonical,digest,unique_json
from scripts.banking_sdk_worker import worker_template
from scripts.a2a_worker_identity import template_hash,verify_pod,verify_terminal_worker
from scripts.a2a_sdk_transport import SDKWorkerTransport
from scripts.banking_sdk_worker_stream import BankingWorkerStream
from scripts import banking_allowance
from scripts.unattended_model_guard import APPROVED_UPSTREAM
from scripts.banking_sdk_guard_ledger import validate_banking_guard_ledger
from scripts.banking_sdk_billing_policy import require_provider_authorization


class KubernetesBankingBackend:
    def __init__(self,*,api,admission,policy,state_root,placement_observer,provider_policy_verifier,
                 stream_factory=BankingWorkerStream,transport_factory=SDKWorkerTransport,clock=time.time,observation_seconds=5,owner_check=True):
        if not callable(placement_observer) or not callable(provider_policy_verifier) or digest(policy)!=admission.get('backendPolicySha256'):
            raise ValueError('EXACT_BANKING_BACKEND_POLICY_REQUIRED')
        expected={'namespace','namespaceUID','nodeName','workspaceClaim','workspaceClaimUID','workspaceSubpath','credentialSecret','guardClaim','guardSubpath','serviceAccount','serviceAccountUID','imageRepository','project'}
        if not isinstance(policy,dict) or set(policy)!=expected or policy['namespace']!=api.namespace or policy['namespaceUID']!=api.namespace_uid or policy['guardClaim']!=admission['storage']['claim'] or policy['guardSubpath']!=admission['storage']['subpath'] or policy['namespace']!=admission['storage']['namespace']:
            raise ValueError('BANKING_BACKEND_STORAGE_PLACEMENT_REFUSED')
        if policy['serviceAccount']!='dsh-banking-sdk-worker':raise ValueError('DEDICATED_BANKING_WORKER_ACCOUNT_REQUIRED')
        if policy['namespace']!='llm' or policy['guardClaim']!='dsh-banking-protected-guard-state':raise ValueError('CANONICAL_BANKING_GUARD_STORE_REQUIRED')
        if api.allowed_claims!={policy['workspaceClaim']:policy['workspaceClaimUID'],policy['guardClaim']:admission['storage']['claimUID']}:
            raise ValueError('BANKING_BACKEND_CLAIM_UIDS_REQUIRED')
        self.api=api;self.admission=copy.deepcopy(admission);self.policy=copy.deepcopy(policy);self.root=Path(state_root)
        self.placement_observer=placement_observer;self.verify_provider=provider_policy_verifier;self.stream_factory=stream_factory;self.transport_factory=transport_factory;self.clock=clock
        if type(observation_seconds) not in (int,float) or not 0<observation_seconds<=15:raise ValueError('BOUNDED_BANKING_OBSERVATION_REQUIRED')
        self.observation_seconds=observation_seconds;self.owner_check=owner_check;self.records={};self.guard_streams={};self.transports={}
    def observe_placement(self):return self.placement_observer()
    def _path(self,id):return self.root/(id+'.backend.json')
    def _save(self,id,row):
        # Distinct controller WAL; never the global request budget.
        banking_allowance._write(self._path(id),{'backend':row})
    def _row(self,id):
        value=unique_json(self._path(id).read_text())
        if not isinstance(value,dict) or set(value)!={'kind','tasks'} or set(value['tasks'])!={'backend'}:raise ValueError('BANKING_BACKEND_WAL_REQUIRED')
        row=value['tasks']['backend']
        original=unique_json((self.root/(id+'.backend.original.json')).read_text())
        if not isinstance(original,dict) or any(row.get(k)!=original.get(k) for k in ('taskId','binding','admission','policy','template','cap')):
            raise ValueError('BANKING_BACKEND_ORIGINAL_BINDING_CHANGED')
        if row.get('phase') not in {'pod-create-reserved','grant-create-reserved','guard-attach-reserved','guard-ready','control-reserved','launch-reserved','running','stop-reserved','stopped','guard-closed-uncertain'}:
            raise ValueError('BANKING_BACKEND_WAL_PHASE_REFUSED')
        if row['phase'] not in {'pod-create-reserved','grant-create-reserved'}:
            physical=unique_json((self.root/(id+'.backend.physical.original.json')).read_text())
            if physical!={k:row.get(k) for k in ('workerPodUID','grantUID','grant','template','binding','cap')}:
                raise ValueError('BANKING_BACKEND_ORIGINAL_WORKER_CHANGED')
        if row.get('admission')!=self.admission or row.get('policy')!=self.policy or row.get('taskId')!=id:raise ValueError('BANKING_BACKEND_ORIGINAL_CHANGED')
        return row
    def _template(self,binding,cap):
        if binding['project']!=self.policy['project']:raise ValueError('BANKING_WORKSPACE_PROJECT_CHANGED')
        policy={k:v for k,v in self.policy.items() if k not in {'workspaceClaimUID','project','serviceAccountUID'}}
        operation=digest(dict(scope=self.admission['scopeDigest'],task=binding['taskId'],binding=binding))[:32]
        return worker_template(admission=self.admission,binding=binding,cap=cap,policy=policy,create_operation=operation)
    def plan_worker(self,*,binding,max_requests,admission):
        if admission!=self.admission:raise ValueError('BANKING_BACKEND_ADMISSION_CHANGED')
        template=self._template(binding,max_requests)
        return dict(templateSha256=template_hash(template),controllerPodUID=admission['placement']['controllerPodUID'])
    def _verify_provider(self):
        proof=self.verify_provider(self.admission['providerPolicyReference'],self.admission['billingAuthorizationReference'])
        authorization_kind,authorization=require_provider_authorization(proof,clock=self.clock)
        expected=dict(**{authorization_kind:authorization},providerPolicyReference=self.admission['providerPolicyReference'],billingAuthorizationReference=self.admission['billingAuthorizationReference'],verified=True,upstream=APPROVED_UPSTREAM,credentialSecret=self.policy['credentialSecret'],namespace=self.policy['namespace'])
        if not isinstance(proof,dict) or proof.get('verified') is not True or proof!=expected:raise ValueError('BANKING_PROVIDER_BILLING_ROUTE_NOT_VERIFIED')
        self.provider_expires=authorization['expiresAt']
        if (self.admission['expiresAt'] is None)!=(self.provider_expires is None):raise ValueError('MIXED_STANDING_PROVIDER_SCOPE')
    def _wait_pod(self,row,*,terminal=False):
        deadline=self.clock()+self.observation_seconds
        while True:
            pod=self.api.read_pod(row['template']['metadata']['name'])
            if pod is None:raise ValueError('BANKING_ORIGINAL_WORKER_ABSENT_NOT_STOP_PROOF')
            try:
                if terminal:
                    proof=verify_terminal_worker(pod,row['template'],pod_uid=row['workerPodUID'],context=row['workerContext'])
                    if proof.get('guardStopped') is not True:raise ValueError('BANKING_GUARD_EXIT_PENDING')
                    return pod,proof
                verify_pod(pod,row['template'],pod_uid=row['workerPodUID'],require_running=True)
                return pod,None
            except ValueError as error:
                # Observe only readiness/init-exit propagation. Identity faults never retry.
                if str(error) not in {'WORKER_RUNNING_CONTAINERS_UNVERIFIED','WORKER_RUNNING_IMAGE_OR_GENERATION_UNVERIFIED','WORKER_INIT_EXIT_UNVERIFIED','BANKING_GUARD_EXIT_PENDING'} or self.clock()>=deadline:raise
                time.sleep(.025)
    def _control(self,row,kind,operation):
        stream=self.guard_streams[row['taskId']]
        stream.send_line(canonical(dict(kind=kind,taskId=row['taskId'],correlationId=row['binding']['correlationId'],workerPodUID=row['workerPodUID'],operationId=operation)).decode())
        return unique_json(stream.receive_line(timeout=5))
    def _physical(self,row):
        return dict(taskId=row['taskId'],correlationId=row['binding']['correlationId'],sourceCommit=self.admission['sourceCommit'],imageDigest=self.admission['imageDigest'],scopeDigest=self.admission['scopeDigest'],grantSha256=row['grant']['grantSha256'],controllerPodUID=self.admission['placement']['controllerPodUID'],workerPodUID=row['workerPodUID'],templateSha256=template_hash(row['template']),storage=copy.deepcopy(self.admission['storage']),cap=row['cap'],endpoint='http://127.0.0.1:4001/v1')
    @contextmanager
    def open_guard(self,*,task,binding,max_requests,admission):
        expected={k:v for k,v in admission.items() if k!='taskGrantSha256'}
        if expected!=self.admission or self._path(task.id).exists() or task.id!=binding['taskId']:raise ValueError('BANKING_BACKEND_REPLAY_OR_ADMISSION_REFUSED')
        self._verify_provider();self.api.read_namespace();self.api.read_account(self.policy['serviceAccount'])
        self.api.read_claim(self.policy['workspaceClaim']);self.api.read_claim(self.policy['guardClaim'])
        task_directory=self.root.parent/self.policy['guardSubpath']/digest({k:binding[k] for k in ('subject','runId','generation','taskId')})
        if self.owner_check:
            info=self.root.parent.stat()
            if os.name!='posix' or info.st_uid!=0 or info.st_mode&0o077:raise ValueError('ROOT_PROTECTED_BANKING_MOUNT_REQUIRED')
        task_directory.mkdir(mode=0o700,parents=True,exist_ok=False)
        if task_directory.is_symlink():raise ValueError('PROTECTED_BANKING_TASK_DIRECTORY_REQUIRED')
        banking_allowance._sync_directory(task_directory.parent)
        template=self._template(binding,max_requests)
        row=dict(taskId=task.id,binding=copy.deepcopy(binding),admission=self.admission,policy=self.policy,template=template,cap=max_requests,phase='pod-create-reserved')
        # Exclusive backend original, including before either POST; no replay on uncertainty.
        fd=os.open(self.root/(task.id+'.backend.original.json'),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as out:out.write(canonical(row));out.flush();os.fsync(out.fileno())
        banking_allowance._sync_directory(self.root);self._save(task.id,row)
        self.api.bind_task(binding=binding,cap=max_requests,template=template)
        pod=self.api.create_once(template);verify_pod(pod,template)
        row.update(workerPodUID=pod['metadata']['uid'],phase='grant-create-reserved')
        grant=dict(kind='DSH_BANKING_SDK_WORKER_GRANT_V1',mode='banking',binding=copy.deepcopy(binding),grantSha256=admission['taskGrantSha256'],scopeDigest=self.admission['scopeDigest'],sourceCommit=self.admission['sourceCommit'],imageDigest=self.admission['imageDigest'],packageAdmissionSha256=self.admission['packageAdmissionSha256'],cap=max_requests,storage=copy.deepcopy(self.admission['storage']),workerPodUID=row['workerPodUID'],controllerPodUID=self.admission['placement']['controllerPodUID'],templateSha256=template_hash(template),expiresAt=None if self.admission['expiresAt'] is None and self.provider_expires is None else min(self.admission['expiresAt'],self.provider_expires),providerPolicyReference=self.admission['providerPolicyReference'],billingAuthorizationReference=self.admission['billingAuthorizationReference'])
        row['grant']=grant;self._save(task.id,row)
        cm=dict(apiVersion='v1',kind='ConfigMap',metadata=dict(name='sdk-bank-grant-'+task.id,namespace=self.api.namespace),immutable=True,data={'grant.json':canonical(grant).decode()})
        result=self.api.create_once(cm)
        if result.get('data')!=cm['data'] or result.get('immutable') is not True:raise ValueError('BANKING_GRANT_CREATE_CONTENT_MISMATCH')
        row.update(grantUID=result['metadata']['uid'],phase='guard-attach-reserved')
        fd=os.open(self.root/(task.id+'.backend.physical.original.json'),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as out:out.write(canonical({k:row[k] for k in ('workerPodUID','grantUID','grant','template','binding','cap')}));out.flush();os.fsync(out.fileno())
        banking_allowance._sync_directory(self.root);self._save(task.id,row)
        self._wait_pod(row)
        stream=self.stream_factory(api=self.api,expected_pod=template,pod_uid=row['workerPodUID'],before_attach=lambda:None,container='model-guard')
        self.guard_streams[task.id]=stream
        try:
            stream.start();status=self._control(row,'status',template['metadata']['annotations']['dsh.example.com/create-operation'])
            want=dict(kind='DSH_BANKING_GUARD_IDENTITY_V1',workerPodUID=row['workerPodUID'],taskId=task.id,correlationId=binding['correlationId'],cap=max_requests,grantSha256=grant['grantSha256'],scopeDigest=grant['scopeDigest'],guardStateIdentity=grant['storage']['guardStateIdentity'])
            if status!=want:raise ValueError('BANKING_ACTUAL_GUARD_CAP_OR_IDENTITY_MISMATCH')
            row.update(phase='guard-ready');self._save(task.id,row)
            guard=SimpleNamespace(task_id=task.id,correlation_id=binding['correlationId'],temperature=0,base_url='http://127.0.0.1:4001/v1',physical_identity=self._physical(row),ledger=SimpleNamespace(task_id=task.id,task_correlation_id=binding['correlationId'],maximum=status['cap']))
            yield guard
        finally:
            try:
                current=self._row(task.id)
                if current['phase']!='stopped':
                    try:self._control(current,'fence-and-snapshot',digest(dict(task=task.id,cleanup=True))[:32])
                    finally:
                        transport=self.transports.get(task.id)
                        if transport is not None:transport.close()
                    current['phase']='guard-closed-uncertain';self._save(task.id,current)
                    raise ValueError('BANKING_PHYSICAL_EXIT_UNVERIFIED')
            finally:stream.close()
    def observe_guard(self,*,binding):
        row=self._row(binding['binding']['taskId']);self._wait_pod(row)
        cm=self.api.read_grant('sdk-bank-grant-'+row['taskId'])
        if cm['metadata'].get('uid')!=row['grantUID'] or cm.get('data')!={'grant.json':canonical(row['grant']).decode()}:raise ValueError('BANKING_ORIGINAL_GRANT_CHANGED')
        return self._physical(row)
    def control_transport(self,*,binding,command):
        row=self._row(binding['binding']['taskId'])
        if row['phase']!='guard-ready' or row['taskId'] in self.transports:raise ValueError('BANKING_CONTROL_REPLAY_REFUSED')
        context=dict(subject=row['binding']['subject'],stageId=row['taskId'],correlationId=row['binding']['correlationId'],project=row['binding']['project'],runtime='sdk',scopeUid=row['workerPodUID'])
        row['workerContext']={k:v for k,v in context.items() if k!='scopeUid'};row['phase']='control-reserved';self._save(row['taskId'],row)
        def before_start():
            current=self._row(row['taskId'])
            if current['phase']!='launch-reserved':raise ValueError('BANKING_NATIVE_START_NOT_RESERVED')
        def before_attach():
            current=self._row(row['taskId'])
            if current.get('attachReserved'):raise ValueError('BANKING_ATTACH_REPLAY_REFUSED')
            current['attachReserved']=True;self._save(row['taskId'],current)
        def before_cancel(operation):
            current=self._row(row['taskId'])
            if current.get('stopOperationId')!=operation or current['phase']!='stop-reserved':raise ValueError('BANKING_STOP_NOT_RESERVED')
        stream=self.stream_factory(api=self.api,expected_pod=row['template'],pod_uid=row['workerPodUID'],before_attach=before_attach)
        transport=self.transport_factory(stream=stream,context=context,timeout_seconds=300 if self.admission['expiresAt'] is None else min(300,self.admission['expiresAt']-self.clock()),before_start=before_start,before_cancel=before_cancel,banking=True)
        self.transports[row['taskId']]=transport;return transport
    def start_once(self,*,harness,context,binding):
        row=self._row(binding['binding']['taskId'])
        if row['phase']!='control-reserved':raise ValueError('BANKING_START_REPLAY_REFUSED')
        row.update(phase='launch-reserved',launchOperationId=context['operationId']);self._save(row['taskId'],row)
        harness.start();self._wait_pod(row)
        current=self._row(row['taskId'])
        if current['phase']!='launch-reserved':raise ValueError('BANKING_START_AFTER_FENCE')
        current['phase']='running';self._save(row['taskId'],current)
        return dict(started=True,runtimeIdentity=self._physical(current))
    def stop_once(self,*,harness,context,binding):
        row=self._row(binding['binding']['taskId'])
        if row['phase'] in {'stop-reserved','stopped'} or row.get('launchOperationId',context['launchOperationId'])!=context['launchOperationId']:raise ValueError('BANKING_STOP_REPLAY_OR_FOREIGN_LAUNCH')
        idle=row['phase'] in {'guard-ready','control-reserved'}
        row.update(phase='stop-reserved',launchOperationId=context['launchOperationId'],stopOperationId=context['operationId']);self._save(row['taskId'],row)
        transport=self.transports.get(row['taskId'])
        if transport is None and not idle:raise ValueError('BANKING_ORIGINAL_TRANSPORT_MISSING')
        # Fence model forwarding BEFORE cancelling/stopping the payload.
        fence=self._control(row,'fence-and-snapshot',context['operationId'])
        if fence.get('localInflightDrained') is not True or fence.get('providerExecutionStoppedVerified') is not False or fence.get('kind')!='DSH_BANKING_GUARD_FENCE_V1' or any(fence.get(k)!=v for k,v in dict(taskId=row['taskId'],workerPodUID=row['workerPodUID'],correlationId=row['binding']['correlationId'],operationId=context['operationId'],grantSha256=row['grant']['grantSha256'],scopeDigest=row['grant']['scopeDigest'],localInflightDrained=True,providerExecutionStoppedVerified=False).items()):raise ValueError('BANKING_GUARD_FENCE_UNVERIFIED')
        rows=validate_banking_guard_ledger(SimpleNamespace(id=row['taskId'],correlation_id=row['binding']['correlationId']),b'\n'.join(canonical(v) for v in fence.get('rows',[])),cap=row['cap'],fence_operation=context['operationId'])
        if digest(rows)!=fence.get('ledgerSha256'):raise ValueError('BANKING_GUARD_LEDGER_DIGEST_MISMATCH')
        row['fence']=fence;self._save(row['taskId'],row)
        if idle:
            if transport is not None:transport.close()
            row['workerContext']=dict(subject=row['binding']['subject'],stageId=row['taskId'],correlationId=row['binding']['correlationId'],project=row['binding']['project'],runtime='sdk')
            row['idleCancelAttachReserved']=True;self._save(row['taskId'],row)
            idle_stream=self.stream_factory(api=self.api,expected_pod=row['template'],pod_uid=row['workerPodUID'],before_attach=lambda:None,banking_idle_cancel=True)
            try:
                idle_stream.start()
                idle_stream.send_line(canonical(dict(kind='banking-idle-cancel',context=dict(row['workerContext'],scopeUid=row['workerPodUID']),operationId=context['operationId'],grantSha256=row['grant']['grantSha256'])).decode())
                terminal=unique_json(idle_stream.receive_line(timeout=5))
                if terminal.get('kind')!='terminal' or terminal.get('receipt',{}).get('neverStarted') is not True:raise ValueError('BANKING_IDLE_STOP_RECEIPT_UNVERIFIED')
            finally:idle_stream.close()
        else:transport.cancel_once(context['operationId'])
        pod,proof=self._wait_pod(row,terminal=True)
        if proof.get('processExitVerified') is not True or proof.get('descendantAbsenceVerified') is not True or proof.get('operationId')!=context['operationId'] or proof.get('guardStopped') is not True:raise ValueError('BANKING_PHYSICAL_STOP_UNVERIFIED')
        receipt=dict(context,launchFenced=True,stopped=True,processExitVerified=True,descendantAbsenceVerified=True,runtimeIdentity=self._physical(row))
        if idle:receipt['neverStarted']=True
        row.update(phase='stopped',receipt=receipt,terminalWorkerProof=copy.deepcopy(proof));self._save(row['taskId'],row)
        if harness is not None:harness.client.close()
        return receipt
    def inspect_exit(self,*,context,binding):
        row=self._row(binding['binding']['taskId'])
        if row['phase']!='stopped' or not isinstance(row.get('receipt'),dict):raise ValueError('BANKING_SAVED_STOP_UNVERIFIED')
        self.api.bind_recovery_read(template=row['template'],pod_uid=row['workerPodUID'],grant_name='sdk-bank-grant-'+row['taskId'],grant_uid=row['grantUID'])
        pod=self.api.read_pod(row['template']['metadata']['name'])
        if pod is not None:verify_terminal_worker(pod,row['template'],pod_uid=row['workerPodUID'],context=row['workerContext'])
        # A saved verified stop is the proof; later Pod absence alone never is.
        return copy.deepcopy(row['receipt'])
