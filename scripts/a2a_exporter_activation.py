"""Disabled-by-default protected exporter lifecycle; explicit adapters only.

No socket, thread, credential loader or automatic recovery start. Only the
existing Task controller writes intent/result files. The injected listener
must implement exact one-shot start/stop and authoritative state observation.
Source tests of that contract never qualify a real listener or deployment.
"""
import copy
import hashlib
import re
from scripts.a2a_provider_exporter import ROUTE,TLSProviderMetadataQuery
from scripts.a2a_worker_retirement import read_record,write_once

START='a2a-exporter-activation-intent.json'
ACTIVE='a2a-exporter-activation-result.json'
STOP='a2a-exporter-inactive-intent.json'
INACTIVE='a2a-exporter-inactive-result.json'


class ProtectedExporterActivation:
    def __init__(self,*,runtime,task,lease_reader,identity_observer,listener):
        if (not callable(lease_reader) or not callable(identity_observer)
                or any(not callable(getattr(listener,k,None)) for k in ('observe','start_once','stop_once'))):
            raise ValueError('EXPLICIT_SCOPED_ACTIVATION_DEPENDENCIES_REQUIRED')
        self.runtime,self.factory,self.task=runtime,runtime.factory,task
        self.read,self.identity,self.listener=lease_reader,identity_observer,listener
        # Construction never reads identity, writes state or starts a listener.

    def _check(self,*,cleanup=False):
        r,f,t=self.runtime,self.factory,self.task
        if (getattr(f,'provider_capture_runtime',None) is not r
                or f.registry.tasks.get(t.id) is not t
                or t.authenticated_subject!=f.sdk.subject or f.observe()!=f.placement
                or (not cleanup and t.state!='running')):
            raise ValueError('CANONICAL_PROTECTED_ACTIVATION_OWNER_REQUIRED')
        identity=self.identity()
        fields={'kind','origin','subject','namespace','namespaceUID','generation','certificateSha256','approvalSha256'}
        if (not isinstance(identity,dict) or set(identity)!=fields
                or identity['kind']!='DSH_SCOPED_EXPORTER_IDENTITY_V1'
                or identity['origin']!='explicit-injected'
                or any(identity[k]!=v for k,v in dict(subject=f.sdk.subject,namespace=f.sdk.api.namespace,
                    namespaceUID=f.sdk.api.namespace_uid,generation=f.sdk.generation).items())
                or any(not re.fullmatch(r'[a-f0-9]{64}',str(identity[k])) or identity[k]=='0'*64
                       for k in ('certificateSha256','approvalSha256'))):
            raise ValueError('APPROVED_EXPLICIT_SCOPED_IDENTITY_REQUIRED')
        peer=r.exporter.read()
        if (not isinstance(peer,dict) or set(peer)!={'subject','namespace','namespaceUID','generation',
                'controllerCertificateSha256','expiresAt'}
                or any(peer.get(k)!=identity[k] for k in ('subject','namespace','namespaceUID','generation'))
                or peer.get('controllerCertificateSha256')!=identity['certificateSha256']
                or type(peer.get('expiresAt')) not in (int,float)
                or not 0<peer['expiresAt'] or peer['expiresAt']-r.clock()>300
                or (not cleanup and peer['expiresAt']<=r.clock())):
            raise ValueError('ACTIVATION_IDENTITY_EXPORTER_PEER_POLICY_MISMATCH')
        source=copy.deepcopy(r.exporter.source)
        if r.exporter.observe()!=source:raise ValueError('EXPORTER_ACTIVATION_SOURCE_CHANGED')
        if type(r.query) is not TLSProviderMetadataQuery:
            raise ValueError('VERIFIED_INTERNAL_EXPORTER_ROUTE_REQUIRED')
        # Revalidate the current route/TLS settings without connecting. A
        # previously valid query object may have been changed after construction.
        TLSProviderMetadataQuery(origin=r.query.origin.geturl(),namespace=f.sdk.api.namespace,
            tls_context=r.query.tls,connection_factory=r.query.connect)
        route=dict(origin=r.query.origin.geturl().rstrip('/'),path=ROUTE,redirects=False)
        scope=dict(taskId=t.id,subject=t.authenticated_subject,generation=f.sdk.generation,
            placement=copy.deepcopy(f.placement),source=source,identity=copy.deepcopy(identity),route=route)
        lease=self.read()
        if (not isinstance(lease,dict) or set(lease)!={'kind','scope','activationId','expiresAt'}
                or lease['kind']!='DSH_EXPORTER_ACTIVATION_LEASE_V1' or lease['scope']!=scope
                or not re.fullmatch(r'[a-f0-9]{32}',str(lease['activationId']))
                or type(lease['expiresAt']) not in (int,float)
                or not 0<lease['expiresAt'] or lease['expiresAt']-r.clock()>300
                or (not cleanup and lease['expiresAt']<=r.clock())):
            raise ValueError('EXACT_FINITE_EXPORTER_ACTIVATION_LEASE_REQUIRED')
        return copy.deepcopy(lease)

    def _locked(self,action,*,cleanup=False):
        with self.factory.registry.lock:
            if not self.task.persistence_lock.acquire(blocking=False):raise ValueError('EXPORTER_ACTIVATION_WRITER_BUSY')
            try:return action(self._check(cleanup=cleanup))
            finally:self.task.persistence_lock.release()

    def _observation(self,lease,state):
        expected=dict(kind='DSH_EXPORTER_LISTENER_OBSERVATION_V1',state=state,
            activationId=lease['activationId'],scope=lease['scope'])
        if self.listener.observe()!=expected:raise ValueError('EXACT_EXPORTER_LISTENER_STATE_UNVERIFIED')
        return expected

    def _intent(self,lease):
        raw,value=read_record(self.task,START)
        if value!=dict(kind='DSH_EXPORTER_ACTIVATION_INTENT_V1',lease=lease):
            raise ValueError('EXPORTER_ACTIVATION_INTENT_CHANGED')
        return hashlib.sha256(raw).hexdigest()

    def activate(self):
        def reserve(lease):
            path=self.task.directory/START
            if path.exists() or path.is_symlink():
                raise ValueError('EXPORTER_ACTIVATION_CONSUMED_NO_RESTART')
            # Readback of the one listener must be inactive for this exact
            # scope. Foreign listeners are never stopped/replaced implicitly.
            self._observation(lease,'inactive')
            write_once(self.task,START,dict(kind='DSH_EXPORTER_ACTIVATION_INTENT_V1',lease=lease))
            self.task.save()
            return lease
        lease=self._locked(reserve)
        self._locked(lambda current:self._same(current,lease))
        self.listener.start_once(copy.deepcopy(lease),handler=self.runtime.handler)
        def finish(current):
            self._same(current,lease);observed=self._observation(lease,'active')
            result=dict(kind='DSH_EXPORTER_ACTIVATION_RESULT_V1',intentSha256=self._intent(lease),observation=observed)
            write_once(self.task,ACTIVE,result);self.task.save()
            return copy.deepcopy(result)
        return self._locked(finish)

    @staticmethod
    def _same(current,lease):
        if current!=lease:raise ValueError('EXPORTER_ACTIVATION_LEASE_CHANGED')

    def recover(self):
        def recover(lease):
            digest=self._intent(lease)
            if (self.task.directory/STOP).exists() or (self.task.directory/STOP).is_symlink():
                raise ValueError('EXPORTER_ROLLBACK_RESERVED_ACTIVE_RECOVERY_REFUSED')
            # A lost start reply/result is deliberately uncertain. Do not
            # start again or manufacture an ACTIVE result from a new process.
            _,result=read_record(self.task,ACTIVE)
            expected=dict(kind='DSH_EXPORTER_ACTIVATION_RESULT_V1',intentSha256=digest,
                observation=self._observation(lease,'active'))
            if result!=expected:raise ValueError('EXPORTER_ACTIVE_RESULT_CHANGED')
            return copy.deepcopy(result)
        return self._locked(recover)

    def rollback_to_inactive(self):
        def reserve(lease):
            digest=self._intent(lease)
            value=dict(kind='DSH_EXPORTER_INACTIVE_INTENT_V1',activationIntentSha256=digest,lease=lease)
            write_once(self.task,STOP,value);self.task.save()
            return lease
        lease=self._locked(reserve,cleanup=True)
        # Cleanup remains possible after the exact activation lease expires.
        # No broadened/renewed identity, route or lease is inferred.
        observed=self.listener.observe()
        inactive=dict(kind='DSH_EXPORTER_LISTENER_OBSERVATION_V1',state='inactive',
            activationId=lease['activationId'],scope=lease['scope'])
        if observed!=inactive:
            self._observation(lease,'active')
            self._locked(lambda current:self._same(current,lease),cleanup=True)
            self.listener.stop_once(copy.deepcopy(lease))
        return self.recover_rollback()

    def recover_rollback(self):
        def finish(lease):
            digest=self._intent(lease)
            raw,intent=read_record(self.task,STOP)
            if intent!=dict(kind='DSH_EXPORTER_INACTIVE_INTENT_V1',activationIntentSha256=digest,lease=lease):
                raise ValueError('EXPORTER_INACTIVE_INTENT_CHANGED')
            result=dict(kind='DSH_EXPORTER_INACTIVE_RESULT_V1',intentSha256=hashlib.sha256(raw).hexdigest(),
                observation=self._observation(lease,'inactive'),applicationRollbackVerified=False)
            path=self.task.directory/INACTIVE
            if path.exists() or path.is_symlink():
                if read_record(self.task,INACTIVE)[1]!=result:raise ValueError('EXPORTER_INACTIVE_RESULT_CHANGED')
            else:write_once(self.task,INACTIVE,result)
            self.task.save()
            return copy.deepcopy(result)
        return self._locked(finish,cleanup=True)

    def expire(self):
        lease=self._locked(lambda value:value,cleanup=True)
        if lease['expiresAt']>self.runtime.clock():raise ValueError('EXPORTER_LEASE_NOT_EXPIRED')
        return self.rollback_to_inactive()
