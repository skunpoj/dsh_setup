"""Concrete SDK bootstrap bridge over the existing protected A2A factory.

No API client, credentials, runtime download, process or second Task writer is
constructed here. The protected owner binds the actual factory explicitly.
Availability is recomputed from its fresh observed placement/admission, never
from a stored qualified flag. This is not live qualification evidence.
"""
import copy
import re
import threading
from scripts.a2a_factory_contract import ProtectedA2AFactory

PATH='/opt/dsh/scripts/a2a_sdk_scope_factory.py'


def install_protected_a2a_factory(*,registry,factory):
    if type(factory) is not ProtectedA2AFactory or factory.registry is not registry:
        raise ValueError('EXACT_EXISTING_PROTECTED_FACTORY_REQUIRED')
    with registry.lock:
        if getattr(registry,'protected_a2a_factory',None) is not None:
            raise ValueError('PROTECTED_FACTORY_ALREADY_BOUND_NO_REPLACEMENT')
        registry.protected_a2a_factory=factory
    # No admission read, Task write, transport or process start.


class ProtectedSDKScope:
    def __init__(self,*,factory,admission):
        if type(factory) is not ProtectedA2AFactory:
            raise ValueError('EXACT_EXISTING_PROTECTED_FACTORY_REQUIRED')
        keys={'kind','mode','subject','generation','expiresAt','sourceCommit','imageDigest',
            'packageAdmissionSha256','scopeModule','scopeSha256','sources','deploymentBinding'}
        if (not isinstance(admission,dict) or set(admission)!=keys
                or admission['kind']!='DSH_OFFICIAL_SDK_SERVER_ADMISSION_V1'
                or admission['mode']!='qualification' or admission['scopeModule']!=PATH
                or not isinstance(admission['sources'],dict)
                or not re.fullmatch(r'[a-f0-9]{64}',str(admission['scopeSha256']))
                or not re.fullmatch(r'[a-f0-9]{64}',str(admission['sources'].get('controller')))):
            raise ValueError('EXACT_VERIFIED_BOOTSTRAP_DESCRIPTOR_REQUIRED')
        self.factory=factory;self.admission=copy.deepcopy(admission)
        self.lock=threading.RLock();self.bound={}

    def _bindings(self):
        f=self.factory;c=self.admission
        if getattr(f.registry,'protected_a2a_factory',None) is not f:
            raise ValueError('PROTECTED_FACTORY_OWNER_CHANGED')
        if (f.observe()!=c['deploymentBinding'] or f.placement!=c['deploymentBinding']
                or f.sdk.subject!=c['subject'] or f.sdk.generation!=c['generation']
                or f.sdk.source_commit!=c['sourceCommit']
                or f.sdk.image.split('@')[-1]!=c['imageDigest']
                or f.sdk.package_hash!=c['packageAdmissionSha256']):
            raise ValueError('SDK_SCOPE_SOURCE_IMAGE_PACKAGE_OR_PLACEMENT_CHANGED')

    def _fresh(self):
        f=self.factory;c=self.admission
        self._bindings()
        a=f._fresh()  # Actual injected placement/namespace and finite policy.
        if type(c['expiresAt']) not in (int,float) or not 0<c['expiresAt']-f.clock()<=300:
            raise ValueError('SDK_SCOPE_BOOTSTRAP_DESCRIPTOR_EXPIRED_OR_INVALID')
        if (f.observe()!=c['deploymentBinding'] or f.placement!=c['deploymentBinding']
                or a['subject']!=c['subject'] or a['generation']!=c['generation']
                or a['sourceCommit']!=c['sourceCommit']
                or a['image'].split('@')[-1]!=c['imageDigest']
                or a['packageAdmissionSha256']!=c['packageAdmissionSha256']):
            raise ValueError('SDK_SCOPE_SOURCE_IMAGE_PACKAGE_OR_PLACEMENT_CHANGED')
        return a

    def admission_state(self,subject,generation):
        a=self._fresh();c=self.admission
        if (subject,generation)!=(c['subject'],c['generation']):
            raise ValueError('FOREIGN_SDK_SCOPE_SUBJECT_OR_GENERATION')
        # Bootstrap independently rereads pinned source/package bytes. Physical
        # worker profile/isolation is checked again by the controller at start.
        return dict(admitted=True,subject=subject,generation=generation,
            sourceCommit=c['sourceCommit'],imageDigest=c['imageDigest'],
            controllerSha256=c['sources']['controller'],scopeSha256=c['scopeSha256'],
            packageAdmissionSha256=c['packageAdmissionSha256'],isolatedControl=True,
            brokerCredentialMounts=False,expiresAt=min(a['expiresAt'],c['expiresAt']))

    @property
    def qualified(self):
        try:
            self.admission_state(self.admission['subject'],self.admission['generation'])
            return True
        except Exception:return False

    def _task(self,context,*,fresh=True):
        if fresh:self._fresh()
        if not isinstance(context,dict):raise ValueError('EXACT_SDK_SCOPE_CONTEXT_REQUIRED')
        task=self.factory.lookup(context.get('taskId'))
        if task is None:raise ValueError('EXISTING_SDK_SCOPE_TASK_REQUIRED')
        expected=dict(subject=self.factory.sdk.subject,generation=self.factory.sdk.generation,
            taskId=task.id,sessionId=task.id,project=task.request['project'],correlationId=task.correlation_id)
        if (task.authenticated_subject!=expected['subject'] or task.request.get('runtime')!='sdk'
                or task.request.get('backend')!='private'
                or any(context.get(k)!=v for k,v in expected.items())):
            raise ValueError('FOREIGN_SDK_SCOPE_TASK_BINDING')
        return task,expected

    def preflight(self,context):
        task,expected=self._task(context)
        if context!=expected or task.state!='running':raise ValueError('EXACT_RUNNING_SDK_PREFLIGHT_REQUIRED')
        with self.lock:
            if task.id in self.bound:raise ValueError('SDK_PREFLIGHT_CONSUMED_NO_REBIND')
            components=self.factory.bind(task)
            self.bound[task.id]=(task,components)
        return dict(expected,admitted=True,packageAdmissionSha256=self.factory.sdk.package_hash)

    def _bound(self,context,*,cleanup=False):
        if cleanup:self._bindings()
        task,_=self._task(context,fresh=not cleanup)
        with self.lock:record=self.bound.get(task.id)
        if record is None or record[0] is not task:
            raise ValueError('EXACT_EXISTING_SDK_PREFLIGHT_REQUIRED')
        return record[1]

    def guard_factory(self,task):
        context=dict(subject=self.factory.sdk.subject,generation=self.factory.sdk.generation,
            taskId=task.id,sessionId=task.id,project=task.request['project'],correlationId=task.correlation_id)
        components=self._bound(context)
        if self.factory.lookup(task.id) is not task:raise ValueError('SDK_GUARD_TASK_REPLACED')
        return components['guard_factory']()

    def control_transport(self,*,binding,command):
        return self._bound(binding)['lifecycle'].control_transport(binding=binding,command=command)

    def start(self,harness,context):
        return self._bound(context)['lifecycle'].start(harness,context)

    def stop_and_verify(self,harness,context):
        return self._bound(context,cleanup=True)['lifecycle'].stop_and_verify(harness,context)

    def inspect_exit(self,context):
        # Restart recovery has no new preflight/guard/start. Validate the exact
        # current placement and retained native binding through the controller.
        self._bindings()
        task,_=self._task(context,fresh=False)
        if self.factory.observe()!=self.factory.placement:
            raise ValueError('PROTECTED_FACTORY_PLACEMENT_CHANGED')
        return self.factory.sdk_lifecycle.inspect_exit(context)


def build_official_sdk_scope(*,registry,admission):
    factory=getattr(registry,'protected_a2a_factory',None)
    if type(factory) is not ProtectedA2AFactory or factory.registry is not registry:
        raise ValueError('EXPLICIT_PROTECTED_FACTORY_BINDING_REQUIRED')
    scope=ProtectedSDKScope(factory=factory,admission=admission)
    return dict(scope=scope,guardFactory=scope.guard_factory)
