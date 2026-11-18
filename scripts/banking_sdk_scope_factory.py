"""Proposed distinct banking scope. Never registered by native qualification.

Protected composition supplies descriptor reader, independent placement observer,
canonical task lookup and physical worker backend. No discovery, credentials,
network, process, PVC or default runtime admission is performed here. Live
references must be bound by the owner; the offline fixture is not a deployment.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import tempfile
import time
from contextlib import contextmanager
from scripts import banking_allowance
from scripts.official_sdk_banking_guard import SDKBankingGuardFactory


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def unique_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value: raise ValueError("BANKING_DUPLICATE_FIELD")
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda x: (_ for _ in ()).throw(ValueError("BANKING_NONFINITE_JSON")))


class BankingSDKScope:
    """One server descriptor, one task owner, durable original and launch journal.

    backend must implement observe_placement(), open_guard(task,binding,
    max_requests,admission), control_transport(binding,command), start_once(...),
    stop_once(...), inspect_exit(...). It owns physical creation and guard drain;
    every returned physical receipt is independently compared below. No retries.
    """
    KEYS = {"kind", "mode", "authenticatedSubject", "generation", "runId", "expiresAt",
        "sourceCommit", "sourceHashes", "imageDigest", "packageAdmissionSha256", "backendPolicySha256", "qualificationReceiptSha256", "placement",
        "storage", "providerPolicyReference", "billingAuthorizationReference", "scopeDigest"}
    def __init__(self, *, descriptor_reader, backend, task_lookup, state_root, source_observer, clock=time.time, owner_check=True, recovery_only=False):
        if not callable(descriptor_reader) or not callable(task_lookup) or not callable(source_observer):
            raise ValueError("EXPLICIT_BANKING_SCOPE_DEPENDENCIES_REQUIRED")
        for method in ("observe_placement", "plan_worker", "observe_guard", "open_guard", "control_transport", "start_once", "stop_once", "inspect_exit"):
            if not callable(getattr(backend, method, None)):
                raise ValueError("COMPLETE_BANKING_PHYSICAL_BACKEND_REQUIRED")
        self.read, self.backend, self.lookup, self.clock = descriptor_reader, backend, task_lookup, clock
        self.source_observer=source_observer
        self.recovery_only=recovery_only
        self.root=Path(state_root);self.owner_check=owner_check;self.lock=threading.RLock()
        if self.root.is_symlink() or not self.root.is_dir():raise ValueError("BOUND_PROTECTED_BANKING_STATE_REQUIRED")
        info=self.root.stat()
        if owner_check and (os.name != "posix" or info.st_uid != 0 or info.st_mode & 0o077):
            raise ValueError("PROTECTED_BANKING_STATE_OWNER_REQUIRED")
        self.original=self._validate(self.read(),allow_expired=recovery_only);self.scope_digest=self.original['scopeDigest']
        self.bound={}
    def _validate(self, value, *, allow_expired=False):
        if not isinstance(value,dict) or set(value)!=self.KEYS or value.get("kind")!="DSH_BANKING_SDK_SCOPE_V1" or value.get("mode")!="banking":
            raise ValueError("EXACT_DISTINCT_BANKING_DESCRIPTOR_REQUIRED")
        for key in ("authenticatedSubject","generation","runId"):
            if not isinstance(value[key],str) or not re.fullmatch(r"[A-Za-z0-9_.@:-]{1,128}",value[key]):
                raise ValueError("BANKING_DESCRIPTOR_IDENTITY_REQUIRED")
        for key,size in (("sourceCommit",40),("imageDigest",64),("packageAdmissionSha256",64),("scopeDigest",64),("backendPolicySha256",64),("qualificationReceiptSha256",64)):
            if not isinstance(value[key],str) or value[key]=='0'*size or not re.fullmatch(r"[a-f0-9]{%d}"%size,value[key]):raise ValueError("BANKING_DESCRIPTOR_DIGEST_REQUIRED")
        for key in ("placement","storage","sourceHashes"):
            if not isinstance(value[key],dict) or not value[key]:raise ValueError("BANKING_UNBOUND_DESCRIPTOR")
        if set(value['storage'])!={'claim','claimUID','namespace','subpath','globalLedgerIdentity','guardStateIdentity'} or any(not isinstance(v,str) or not v for v in value['storage'].values()):
            raise ValueError("BANKING_UNBOUND_STORAGE")
        if (set(value['placement'])!={'namespace','namespaceUID','controllerPodUID','workloadUID','environment','workloadRole'}
                or value['placement']['environment']!='test' or value['placement']['workloadRole']!='banking'):
            raise ValueError("DISTINCT_BANKING_PLACEMENT_REQUIRED")
        for key in ('namespaceUID','controllerPodUID','workloadUID'):
            if not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',str(value['placement'][key])):
                raise ValueError("BANKING_PLACEMENT_UID_REQUIRED")
        if not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',value['storage']['claimUID']):
            raise ValueError("BANKING_STORAGE_UID_REQUIRED")
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}(?:/[A-Za-z0-9_-]{1,128}){0,3}',value['storage']['subpath']):
            raise ValueError("BANKING_STORAGE_SUBPATH_REQUIRED")
        if set(value['sourceHashes'])!={'scope','controller','runner','guard','backend'}:raise ValueError('COMPLETE_BANKING_SOURCE_BINDING_REQUIRED')
        if any(not isinstance(k,str) or not isinstance(v,str) or not re.fullmatch(r'[a-f0-9]{64}',v) for k,v in value['sourceHashes'].items()):
            raise ValueError("BANKING_SOURCE_DIGEST_REQUIRED")
        for key in ("providerPolicyReference","billingAuthorizationReference"):
            if not isinstance(value[key],str) or not value[key]:raise ValueError("BANKING_UNBOUND_PROVIDER_POLICY")
        if value['expiresAt'] is not None and (type(value['expiresAt']) not in (int,float) or (not allow_expired and not 0<value['expiresAt']-self.clock()<=300)):
            raise ValueError("BANKING_SCOPE_EXPIRED")
        without={k:v for k,v in value.items() if k!='scopeDigest'}
        if digest(without)!=value['scopeDigest']:raise ValueError("BANKING_SCOPE_DIGEST_MISMATCH")
        return copy.deepcopy(value)
    def _fresh(self):
        if self.recovery_only:raise ValueError('BANKING_RECOVERY_ONLY_NO_ADMISSION')
        value=self._validate(self.read())
        if canonical(value)!=canonical(self.original):raise ValueError("BANKING_ORIGINAL_ADMISSION_CHANGED")
        if self.source_observer()!=value['sourceHashes']:raise ValueError("BANKING_PROTECTED_SOURCE_CHANGED")
        if self.backend.observe_placement()!=value['placement']:raise ValueError("BANKING_PLACEMENT_CHANGED")
        return value
    @property
    def qualified(self):
        try:self._fresh();return True
        except Exception:return False
    def admission_state(self,subject,generation):
        value=self._fresh()
        if (subject,generation)!=(value['authenticatedSubject'],value['generation']):raise ValueError("FOREIGN_BANKING_SCOPE")
        return dict(admitted=True,subject=subject,generation=generation,sourceCommit=value['sourceCommit'],
            imageDigest=value['imageDigest'],controllerSha256=value['sourceHashes'].get('controller'),
            scopeSha256=value['sourceHashes'].get('scope'),packageAdmissionSha256=value['packageAdmissionSha256'],
            isolatedControl=True,brokerCredentialMounts=False,expiresAt=value['expiresAt'])
    def _task(self,context,*,cleanup=False):
        if cleanup:
            value=self.original
            if self.source_observer()!=value['sourceHashes'] or self.backend.observe_placement()!=value['placement']:
                raise ValueError('BANKING_CLEANUP_ORIGINAL_PLACEMENT_CHANGED')
        else:value=self._fresh()
        task=self.lookup(context.get('taskId'))
        if task is None:raise ValueError("CANONICAL_BANKING_TASK_REQUIRED")
        expected=dict(subject=value['authenticatedSubject'],generation=value['generation'],taskId=task.id,
            sessionId=task.id,project=task.request.get('project'),correlationId=task.correlation_id)
        if task.authenticated_subject!=expected['subject'] or task.request.get('runtime')!='sdk' or task.request.get('backend')!='private' or any(context.get(k)!=v for k,v in expected.items()):
            raise ValueError("FOREIGN_BANKING_TASK_BINDING")
        return task,expected
    @contextmanager
    def _locked_task(self,task):
        with self.lock:
            handle=open(self.root/(task.id+'.lock'),'a+b')
            try:
                if os.name=='nt':
                    import msvcrt
                    handle.seek(0,2)
                    if handle.tell()==0:handle.write(b'0');handle.flush()
                    handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_LOCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle,fcntl.LOCK_EX)
                yield
            finally:
                if os.name=='nt':handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(handle,fcntl.LOCK_UN)
                handle.close()
    def _path(self,task):return self.root/(task.id+'.json')
    def _persist(self,task,row):
        fd,name=tempfile.mkstemp(prefix='.sdk-bank-wal-',dir=self.root)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(canonical(dict(kind='DSH_BANKING_SDK_TASK_WAL_V1',tasks={'state':row})))
                stream.flush();os.fsync(stream.fileno())
            os.replace(name,self._path(task))
            if os.name=='posix':
                directory=os.open(self.root,os.O_RDONLY)
                try:os.fsync(directory)
                finally:os.close(directory)
        finally:
            if os.path.exists(name):os.unlink(name)
    def _reload(self,task,*,cleanup=False):
        value=unique_json(self._path(task).read_text())
        if not isinstance(value,dict) or set(value)!={'kind','tasks'} or value['kind']!='DSH_BANKING_SDK_TASK_WAL_V1' or not isinstance(value['tasks'],dict) or set(value['tasks'])!={'state'}:
            raise ValueError("BANKING_WAL_SCHEMA_REFUSED")
        row=value['tasks']['state']
        required={'binding','originalAdmission','scopeDigest','phase','physical','cap'}
        if (not isinstance(row,dict) or not required<=set(row)<=required|{'grantSha256','receipt','launchOperationId','stopOperationId','plannedTemplateSha256'}
                or row['phase'] not in {'admitted','physical-reserved','guard-ready','launch-reserved','running','stop-reserved','stopped'}
                or (row['phase']!='admitted' and (row['cap'] is not None and (type(row['cap']) is not int or not 2<=row['cap']<=32)
                    or not re.fullmatch(r'[a-f0-9]{64}',str(row.get('grantSha256')))))):
            raise ValueError('BANKING_WAL_STATE_SCHEMA_REFUSED')
        if row['physical'] is not None:
            physical_original=unique_json((self.root/(task.id+'.physical.original.json')).read_text())
            if physical_original!={'binding':row['binding'],'physical':row['physical'],'scopeDigest':self.scope_digest,'grantSha256':row.get('grantSha256')}:
                raise ValueError('BANKING_ORIGINAL_PHYSICAL_IDENTITY_CHANGED')
        original=unique_json((self.root/(task.id+'.original.json')).read_text())
        if not isinstance(original,dict) or original!={'binding':row.get('binding'),'admission':self.original}:
            raise ValueError('BANKING_ORIGINAL_WAL_CHANGED')
        prompt=task.request.get('prompt')
        if not isinstance(prompt,str) and not (cleanup or self.recovery_only):raise ValueError('BANKING_RAW_PROMPT_REQUIRED_FOR_LAUNCH')
        prompt_hash=hashlib.sha256(prompt.encode()).hexdigest() if isinstance(prompt,str) else original['binding']['promptSha256']
        if not re.fullmatch(r'[a-f0-9]{64}',str(prompt_hash)):raise ValueError('BANKING_ORIGINAL_PROMPT_DIGEST_REQUIRED')
        expected=dict(subject=self.original['authenticatedSubject'],generation=self.original['generation'],
            taskId=task.id,project=task.request.get('project'),correlationId=task.correlation_id,runtime='sdk',runner='official-native-sdk',
            runId=self.original['runId'],writes=task.request.get('writes'),
            promptSha256=prompt_hash)
        bound={'binding':expected}
        if task.authenticated_subject!=expected['subject']:raise ValueError('BANKING_RECOVERY_OWNER_CHANGED')
        if bound is None or not isinstance(row,dict) or row.get('originalAdmission')!=self.original or row.get('binding')!=bound['binding'] or row.get('scopeDigest')!=self.scope_digest:
            raise ValueError("BANKING_WAL_ORIGINAL_IDENTITY_CHANGED")
        return row
    def preflight(self,context):
        task,expected=self._task(context)
        if context!=expected or task.state!='running':raise ValueError("EXACT_RUNNING_BANKING_PREFLIGHT_REQUIRED")
        if not isinstance(task.request.get('prompt'),str) or not 1<=len(task.request['prompt'])<=65536 or type(task.request.get('writes')) is not bool:
            raise ValueError('EXACT_BANKING_PROMPT_WRITE_POLICY_REQUIRED')
        with self._locked_task(task):
            if self._path(task).exists() or task.id in self.bound:raise ValueError("BANKING_LAUNCH_REPLAY_REFUSED")
            binding={**{k:v for k,v in expected.items() if k!='sessionId'},'runtime':'sdk','runner':'official-native-sdk','runId':self.original['runId'],'writes':task.request.get('writes'),
                'promptSha256':hashlib.sha256(task.request.get('prompt','').encode()).hexdigest()}
            # Exclusive original reservation survives process restart; no reset.
            original=self.root/(task.id+'.original.json')
            fd=os.open(original,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as stream:
                stream.write(canonical(dict(binding=binding,admission=self.original)));stream.flush();os.fsync(stream.fileno())
            self.bound[task.id]={'binding':binding}
            self._persist(task,dict(binding=binding,originalAdmission=self.original,scopeDigest=self.scope_digest,
                phase='admitted',physical=None,cap=None))
        return dict(expected,admitted=True,packageAdmissionSha256=self.original['packageAdmissionSha256'])
    @contextmanager
    def open_guard(self,*,task,binding,max_requests):
        self._fresh()
        if (max_requests is None)!=(self.original['expiresAt'] is None):raise ValueError('MIXED_STANDING_GUARD_SCOPE')
        with self._locked_task(task):
            row=self._reload(task)
            if row['phase']!='admitted' or any(binding.get(k)!=v for k,v in row['binding'].items() if k!='sessionId'):
                raise ValueError("EXACT_BANKING_GUARD_RESERVATION_REQUIRED")
            if not re.fullmatch(r'[a-f0-9]{64}',str(binding.get('grantSha256'))):raise ValueError('BANKING_EXACT_GRANT_DIGEST_REQUIRED')
            plan=self.backend.plan_worker(binding=copy.deepcopy(row['binding']),max_requests=max_requests,admission=copy.deepcopy(self.original))
            if not isinstance(plan,dict) or set(plan)!={'templateSha256','controllerPodUID'} or plan['controllerPodUID']!=self.original['placement']['controllerPodUID'] or not re.fullmatch(r'[a-f0-9]{64}',str(plan['templateSha256'])):
                raise ValueError('EXACT_BANKING_WORKER_PLAN_REQUIRED')
            row.update(phase='physical-reserved',cap=max_requests,grantSha256=binding['grantSha256'],plannedTemplateSha256=plan['templateSha256']);self._persist(task,row)
        # One reservation before ANY physical opener. Failure stays consumed.
        with self.backend.open_guard(task=task,binding=copy.deepcopy(row['binding']),max_requests=max_requests,admission=dict(copy.deepcopy(self.original),taskGrantSha256=row['grantSha256'])) as guard:
            self._verify_physical(guard.physical_identity,row,max_requests)
            if self.backend.observe_guard(binding=copy.deepcopy(row))!=guard.physical_identity:
                raise ValueError('BANKING_GUARD_OBSERVATION_MISMATCH')
            with self._locked_task(task):
                row=self._reload(task)
                if row['phase']!='physical-reserved':raise ValueError("BANKING_GUARD_RESERVATION_CHANGED")
                original_path=self.root/(task.id+'.physical.original.json')
                fd=os.open(original_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as stream:
                    stream.write(canonical(dict(binding=row['binding'],physical=guard.physical_identity,scopeDigest=self.scope_digest,grantSha256=row['grantSha256'])))
                    stream.flush();os.fsync(stream.fileno())
                banking_allowance._sync_directory(self.root)
                row.update(phase='guard-ready',physical=copy.deepcopy(guard.physical_identity));self._persist(task,row)
            yield guard
    def _verify_physical(self,physical,row,cap):
        expected=dict(taskId=row['binding']['taskId'],correlationId=row['binding']['correlationId'],
            sourceCommit=self.original['sourceCommit'],imageDigest=self.original['imageDigest'],scopeDigest=self.scope_digest,grantSha256=row['grantSha256'],
            controllerPodUID=self.original['placement']['controllerPodUID'],templateSha256=row['plannedTemplateSha256'],storage=copy.deepcopy(self.original['storage']),cap=cap,endpoint='http://127.0.0.1:4001/v1')
        if (not isinstance(physical,dict) or 'cap' not in physical or set(physical)!=set(expected)|{'workerPodUID'}
                or any(physical.get(k)!=v for k,v in expected.items())
                or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',str(physical.get('workerPodUID')))
                or not re.fullmatch(r'[a-f0-9]{64}',str(physical.get('templateSha256')))):
            raise ValueError("BANKING_PHYSICAL_GUARD_IDENTITY_REFUSED")
    def _observe_original_worker(self,row):
        observed=self.backend.observe_guard(binding=copy.deepcopy(row))
        self._verify_physical(observed,row,row['cap'])
        if observed!=row['physical']:raise ValueError('BANKING_ORIGINAL_WORKER_REPLACED')
    def control_transport(self,*,binding,command):
        task,expected=self._task(binding);row=self._reload(task)
        from scripts.official_sdk_control_peer import COMMAND
        if binding!={**expected,'packageAdmissionSha256':self.original['packageAdmissionSha256']} or tuple(command)!=COMMAND:
            raise ValueError('EXACT_OFFICIAL_BANKING_CONTROL_REQUIRED')
        if row['phase']!='guard-ready':raise ValueError("BANKING_CONTROL_BEFORE_VERIFIED_GUARD")
        self._observe_original_worker(row)
        return self.backend.control_transport(binding=copy.deepcopy(row),command=command)
    def start(self,harness,context):
        task,expected=self._task(context)
        native=getattr(task,'native_sdk',None)
        if not isinstance(native,dict) or context!={**expected,'operationId':native.get('launchOperationId')} or not re.fullmatch(r'[a-f0-9]{32}',str(context.get('operationId'))):
            raise ValueError('EXACT_BANKING_LAUNCH_OPERATION_REQUIRED')
        with self._locked_task(task):
            row=self._reload(task)
            if row['phase']!='guard-ready'  or task.state!='running':raise ValueError("BANKING_START_REPLAY_OR_FENCED")
            self._observe_original_worker(row)
            row.update(phase='launch-reserved',launchOperationId=context['operationId']);self._persist(task,row)
        result=self.backend.start_once(harness=harness,context=dict(context),binding=copy.deepcopy(row))
        if not isinstance(result,dict) or result.get('runtimeIdentity')!=row['physical'] or result.get('started') is not True:
            raise ValueError("BANKING_START_IDENTITY_UNVERIFIED")
        with self._locked_task(task):
            row=self._reload(task)
            if row['phase']=='launch-reserved':row.update(phase='running');self._persist(task,row)
            else:raise ValueError("BANKING_START_RACED_WITH_FENCE")
        return {**context,'started':True,'runtimeIdentity':row['physical']}
    def stop_and_verify(self,harness,context):
        task,expected=self._task(context,cleanup=True)
        native=getattr(task,'native_sdk',None)
        if (not isinstance(native,dict) or context!={**expected,'operationId':native.get('stopOperationId'),'launchOperationId':native.get('launchOperationId')}
                or any(not re.fullmatch(r'[a-f0-9]{32}',str(context.get(k))) for k in ('operationId','launchOperationId'))):
            raise ValueError('EXACT_BANKING_STOP_OPERATION_REQUIRED')
        with self._locked_task(task):
            row=self._reload(task,cleanup=True)
            if row['phase'] in {'stop-reserved','stopped'}:raise ValueError("BANKING_STOP_REPLAY_REFUSED")
            if row.get('launchOperationId',context['launchOperationId'])!=context['launchOperationId']:
                raise ValueError('BANKING_ORIGINAL_LAUNCH_OPERATION_CHANGED')
            row.update(phase='stop-reserved',launchOperationId=context['launchOperationId'],stopOperationId=context['operationId']);self._persist(task,row)
        # Backend MUST fence forwarding before stop; uncertain result never succeeds.
        self._observe_original_worker(row)
        receipt=self.backend.stop_once(harness=harness,context=dict(context),binding=copy.deepcopy(row))
        if (not isinstance(receipt,dict) or any(receipt.get(k)!=v for k,v in context.items()) or receipt.get('runtimeIdentity')!=row['physical']
                or any(receipt.get(k) is not True for k in ('launchFenced','stopped','processExitVerified','descendantAbsenceVerified'))):
            raise ValueError("BANKING_STOP_UNCERTAIN")
        with self._locked_task(task):
            row=self._reload(task,cleanup=True);row.update(phase='stopped',receipt=copy.deepcopy(receipt));self._persist(task,row)
        return receipt
    def inspect_exit(self,context):
        task,_=self._task(context,cleanup=True);row=self._reload(task,cleanup=True)
        # Inspect only; never create, replay start/stop, rewrite original or reopen guard.
        observed=self.backend.inspect_exit(context=dict(context),binding=copy.deepcopy(row))
        if row['phase']=='stopped' and observed==row.get('receipt'):return copy.deepcopy(observed)
        raise ValueError("BANKING_RECOVERY_STOP_UNVERIFIED")


def compose_banking_service(*,descriptor_reader,backend,task_lookup,state_root,workspace_root,
        allowance_file,ledger_file,source_observer,runner_factory=None,clock=time.time,owner_check=True,**runner_options):
    scope=BankingSDKScope(descriptor_reader=descriptor_reader,backend=backend,task_lookup=task_lookup,
        state_root=state_root,source_observer=source_observer,clock=clock,owner_check=owner_check)
    value=scope.original
    ledger_parent=Path(ledger_file).resolve().parent
    if owner_check:
        info=ledger_parent.stat()
        if ledger_parent.is_symlink() or os.name!='posix' or info.st_uid!=0 or info.st_mode&0o077:
            raise ValueError('PROTECTED_GLOBAL_BANKING_LEDGER_OWNER_REQUIRED')
    if value['storage']['globalLedgerIdentity']!=str(Path(ledger_file).resolve()):
        raise ValueError('ONE_CANONICAL_BANKING_GLOBAL_LEDGER_REQUIRED')
    adapter=SDKBankingGuardFactory(subject=value['authenticatedSubject'],generation=value['generation'],run_id=value['runId'],
        open_guard=scope.open_guard,allowance_file=allowance_file,ledger_file=ledger_file,owner_check=owner_check)
    if runner_factory is None:
        from scripts.official_sdk_session import OfficialSDKSessionRunner
        runner_factory=OfficialSDKSessionRunner
    return runner_factory(subject=value['authenticatedSubject'],generation=value['generation'],runtime_scope=scope,
        guard_factory=lambda task: (_ for _ in ()).throw(ValueError('BANKING_NATIVE_GUARD_FALLBACK_REFUSED')),
        banking_guard_factory=adapter,workspace_root=workspace_root,**runner_options)


def install_banking_service(server, **composition):
    """Explicit protected entry hook. No auto-discovery or native replacement."""
    if getattr(server,'sdk_service',None) is not None:
        raise ValueError('BANKING_SERVICE_REPLACEMENT_REFUSED')
    service=compose_banking_service(**composition)
    if service.qualified is not True:
        raise ValueError('BANKING_SCOPE_NOT_BOUND')
    # Full original package/source/placement admission, not a label.
    service.fresh_admission()
    server.sdk_service=service
    return service


def compose_banking_recovery(*,original_descriptor_reader,backend,task_lookup,state_root,source_observer,clock=time.time,owner_check=True):
    """Old protected admission only; no runner/guard or route installation."""
    return BankingSDKScope(descriptor_reader=original_descriptor_reader,backend=backend,task_lookup=task_lookup,
        state_root=state_root,source_observer=source_observer,clock=clock,owner_check=owner_check,recovery_only=True)
