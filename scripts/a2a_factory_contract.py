"""Protected Task-writer dependency binding; never a qualification flag.

No new registry/journal, default credentials, worker start, provider call or
fallback. Owner-supplied admission and lifecycle evidence remain mandatory.
"""
import copy
import hashlib
import re
import time
from scripts.a2a_sdk_lifecycle import SDKControllerLifecycle
from scripts.a2a_cli_lifecycle import CLIControllerLifecycle
from scripts.unattended_model_guard import APPROVED_UPSTREAM
from scripts.a2a_factory_budget import reserve_launch

DEPENDENCIES=frozenset({'workspacePolicy','executionAdmission','guardFactory',
                       'providerCapture','retirement','rollback'})
PROVIDER=dict(upstream=APPROVED_UPSTREAM,model='deepseek-v4.1-flash',temperature=0,externalFallback=False)
BUDGET=dict(workerCPU='1',workerMemory='1Gi',guardCPU='250m',guardMemory='256Mi',
            activeDeadlineSeconds=300,taskSeconds=120)


class _BoundLifecycle:
    def __init__(self,lifecycle,current,reserve):self._lifecycle,self._current,self._reserve=lifecycle,current,reserve
    def control_transport(self,**kwargs):
        self._current();return self._lifecycle.control_transport(**kwargs)
    def start(self,*args,**kwargs):
        self._current(model=True);self._reserve();return self._lifecycle.start(*args,**kwargs)
    def execute_once(self,*args,**kwargs):
        self._current(model=True);self._reserve();return self._lifecycle.execute_once(*args,**kwargs)
    def stop_and_verify(self,*args,**kwargs):
        self._current(cleanup=True);return self._lifecycle.stop_and_verify(*args,**kwargs)
    def inspect_exit(self,*args,**kwargs):
        self._current(cleanup=True);return self._lifecycle.inspect_exit(*args,**kwargs)
    def observe_terminal(self,*args,**kwargs):
        self._current(cleanup=True);return self._lifecycle.observe_terminal(*args,**kwargs)


class ProtectedA2AFactory:
    def __init__(self,*,registry,sdk_controller,cli_controller,task_lookup,placement_observer,
                 placement_binding,admission_reader,dependencies,clock=time.time):
        if (not callable(task_lookup) or not callable(placement_observer)
                or not isinstance(getattr(registry,'tasks',None),dict) or not hasattr(getattr(registry,'lock',None),'acquire')
                or not callable(admission_reader) or not isinstance(dependencies,dict)
                or set(dependencies)!=DEPENDENCIES or any(not callable(v) for v in dependencies.values())):
            raise ValueError('COMPLETE_PROTECTED_FACTORY_DEPENDENCIES_REQUIRED')
        if (sdk_controller.api is not cli_controller.api
                or any(getattr(sdk_controller,k)!=getattr(cli_controller,k) for k in
                       ('subject','image','source_commit','node_name'))
                or dependencies['executionAdmission'] is not sdk_controller.execution_admission
                or dependencies['executionAdmission'] is not cli_controller.execution_admission):
            raise ValueError('ONE_PROTECTED_WORKER_API_SOURCE_AND_ADMISSION_REQUIRED')
        required={'namespace','namespaceUID','podUID','workloadUID','environment','workloadRole'}
        if (not isinstance(placement_binding,dict) or set(placement_binding)!=required
                or placement_binding['environment']!='test' or placement_binding['workloadRole']!='qualification'
                or placement_binding['namespace']!=sdk_controller.api.namespace
                or placement_binding['namespaceUID']!=sdk_controller.api.namespace_uid
                or any(not isinstance(placement_binding[k],str) or not re.fullmatch(
                    r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',placement_binding[k])
                    for k in ('namespaceUID','podUID','workloadUID'))):
            raise ValueError('EXACT_PROTECTED_CONTROLLER_PLACEMENT_REQUIRED')
        self.sdk,self.cli=sdk_controller,cli_controller
        self.registry=registry
        self.lookup,self.observe,self.read=task_lookup,placement_observer,admission_reader
        self.placement=copy.deepcopy(placement_binding);self.dependencies=dict(dependencies);self.clock=clock
        self.sdk_lifecycle=SDKControllerLifecycle(controller=self.sdk,task_lookup=self.lookup)
        self.cli_lifecycle=CLIControllerLifecycle(controller=self.cli,task_lookup=self.lookup)

    def _fresh(self):
        if self.observe()!=self.placement:raise ValueError('PROTECTED_FACTORY_PLACEMENT_CHANGED')
        value=self.read()
        expected=dict(subject=self.sdk.subject,generation=self.sdk.generation,
            namespace=self.sdk.api.namespace,namespaceUID=self.sdk.api.namespace_uid,
            nodeName=self.sdk.node_name,image=self.sdk.image,sourceCommit=self.sdk.source_commit,
            packageAdmissionSha256=self.sdk.package_hash,provider=PROVIDER,resourceBudget=BUDGET)
        if (not isinstance(value,dict)
                or set(value)!=set(expected)|{'expiresAt','modelStartsAllowed','rollbackOwner'}
                or any(value.get(k)!=v for k,v in expected.items())
                or type(value['provider'].get('temperature')) not in (int,float)
                or type(value['provider'].get('externalFallback')) is not bool
                or any(type(value['resourceBudget'].get(k)) is not type(v) for k,v in BUDGET.items())
                or type(value['expiresAt']) not in (int,float) or not 0<value['expiresAt']-self.clock()<=300
                or type(value['modelStartsAllowed']) is not int or not 0<=value['modelStartsAllowed']<=3
                or not isinstance(value['rollbackOwner'],str)
                or not re.fullmatch(r'[A-Za-z0-9_.@:-]{1,128}',value['rollbackOwner'])):
            raise ValueError('FINITE_EXACT_PROTECTED_FACTORY_ADMISSION_REQUIRED')
        return copy.deepcopy(value)

    def bind(self,task):
        admission=self._fresh()
        if (self.lookup(task.id) is not task or task.authenticated_subject!=self.sdk.subject
                or task.request.get('backend')!='private'
                or task.request.get('runtime') not in {'sdk','claude','deepagents'}
                or any(not re.fullmatch(r'[a-f0-9]{32}',str(v)) for v in (task.id,task.correlation_id))):
            raise ValueError('EXISTING_AUTHENTICATED_FACTORY_TASK_REQUIRED')
        prompt=task.request.get('prompt')
        if not isinstance(prompt,str) or not 1<=len(prompt)<=65536:
            raise ValueError('EXACT_FACTORY_TASK_PROMPT_REQUIRED')
        controller=self.sdk if task.request['runtime']=='sdk' else self.cli
        policy=self.dependencies['workspacePolicy'](self.sdk.subject,task.request['project'])
        admitted=controller.project_admission(self.sdk.subject,task.request['project'])
        if policy!=admitted:raise ValueError('FACTORY_WORKSPACE_POLICY_CHANGED')
        if (not isinstance(policy,dict) or set(policy)!={'claim','subpath','writes','brokerPath','credentialSecret'}
                or type(policy['writes']) is not bool or type(task.request.get('writes')) is not bool
                or task.request['writes'] and not policy['writes']):
            raise ValueError('EXACT_ADMITTED_WORKSPACE_POLICY_REQUIRED')
        binding=dict(subject=self.sdk.subject,generation=self.sdk.generation,taskId=task.id,
            correlationId=task.correlation_id,project=task.request['project'],runtime=task.request['runtime'],
            writes=task.request['writes'],promptSha256=hashlib.sha256(prompt.encode()).hexdigest())
        def current(*,model=False,cleanup=False):
            if cleanup:
                if self.observe()!=self.placement:raise ValueError('PROTECTED_FACTORY_PLACEMENT_CHANGED')
            elif self._fresh()!=admission:
                raise ValueError('FACTORY_ADMISSION_CHANGED_REBIND_FORBIDDEN')
            if self.lookup(task.id) is not task or task.authenticated_subject!=binding['subject']:
                raise ValueError('FACTORY_TASK_REPLACED_OR_FOREIGN')
            if any(task.request.get(k)!=binding[k] for k in ('project','runtime')) or task.correlation_id!=binding['correlationId']:
                raise ValueError('FACTORY_TASK_BINDING_CHANGED')
            raw=task.request.get('prompt')
            retained=getattr(task,'a2a_cli_worker',None)
            digest=hashlib.sha256(raw.encode()).hexdigest() if isinstance(raw,str) else None
            if (task.request.get('writes') is not binding['writes']
                    or (digest!=binding['promptSha256'] and not (cleanup and raw is None
                        and isinstance(retained,dict) and retained.get('promptSha256')==binding['promptSha256']))):
                raise ValueError('FACTORY_TASK_PROMPT_OR_WRITE_BINDING_CHANGED')
            if not cleanup and (self.dependencies['workspacePolicy'](binding['subject'],binding['project'])!=policy
                    or controller.project_admission(binding['subject'],binding['project'])!=policy):
                raise ValueError('FACTORY_WORKSPACE_POLICY_CHANGED')
            if model and (admission['modelStartsAllowed']<1 or task.state!='running'):
                raise ValueError('FACTORY_MODEL_ALLOWANCE_EXHAUSTED_OR_TASK_FENCED')
        def dependency(name,*args,cleanup=False,**kwargs):
            current(cleanup=cleanup)
            return self.dependencies[name](task,copy.deepcopy(binding),*args,**kwargs)
        def execution_admission(subject,task_id,correlation,project,runtime,writes,prompt_sha):
            current()
            if ((subject,task_id,correlation,project,runtime,writes,prompt_sha)!=
                    (binding['subject'],binding['taskId'],binding['correlationId'],binding['project'],
                     binding['runtime'],binding['writes'],binding['promptSha256']) or type(writes) is not bool):
                raise ValueError('FOREIGN_FACTORY_EXECUTION_ADMISSION_REQUEST')
            return self.dependencies['executionAdmission'](subject,task_id,correlation,project,runtime,writes,prompt_sha)
        # Bound dependencies are not executable qualified services. Their exact
        # evidence still must be verified before task completion/UI exposure.
        return dict(binding=binding,admission=admission,workspace=copy.deepcopy(policy),
            lifecycle=_BoundLifecycle(self.sdk_lifecycle if task.request['runtime']=='sdk' else self.cli_lifecycle,current,
                lambda:reserve_launch(task,registry=self.registry,admission=admission,binding=binding)),
            before_model=lambda:current(model=True),
            execution_admission=execution_admission,
            guard_factory=lambda:dependency('guardFactory'),
            capture_provider=lambda *a,**kw:dependency('providerCapture',*a,cleanup=True,**kw),
            retire=lambda *a,**kw:dependency('retirement',*a,cleanup=True,**kw),
            rollback=lambda *a,**kw:dependency('rollback',*a,cleanup=True,**kw))
