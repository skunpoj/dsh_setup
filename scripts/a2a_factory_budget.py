"""Conservative launch allowances in the existing Task/parent-stage journals.

An allowance reservation is not evidence of an actual provider start. Failed
or uncertain launches are never refunded or replayed automatically. The only
writer is the admitted broker, using its existing Registry and Task locks.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

WAL_NAME='factory-launch-allowance.json'
FIELDS={'subject','generation','taskId','correlationId','runtime','project','writes','promptSha256'}


def sync_directory(directory):
    # Actual qualified controllers are Linux. Windows source tests do not
    # establish directory-fsync or power-loss durability on that platform.
    if os.name=='posix':
        fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)


def read_wal(directory):
    path=Path(directory)/WAL_NAME
    if not path.exists() and not path.is_symlink():return None
    if path.is_symlink():raise ValueError('REGULAR_FACTORY_WRITE_AHEAD_REQUIRED')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0<info.st_size<=4096:
            raise ValueError('BOUNDED_FACTORY_WRITE_AHEAD_REQUIRED')
        with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(4097)
    finally:os.close(fd)
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('DUPLICATE_FACTORY_WRITE_AHEAD_FIELD')
            result[key]=value
        return result
    value=json.loads(raw.decode('utf-8'),object_pairs_hook=unique)
    if (not isinstance(value,dict) or set(value)!=FIELDS|{'kind','reservationId','grantSha256','status'}
            or value['kind']!='DSH_FACTORY_LAUNCH_ALLOWANCE_V1' or value['status']!='reserved'
            or any(not re.fullmatch(r'[a-f0-9]{32}',str(value[k])) for k in ('taskId','correlationId','reservationId'))
            or any(not re.fullmatch(r'[a-f0-9]{64}',str(value[k])) for k in ('grantSha256','promptSha256'))
            or value['taskId']!=Path(directory).name or type(value['writes']) is not bool
            or value['runtime'] not in {'sdk','claude','deepagents'}
            or any(not isinstance(value[k],str) or not re.fullmatch(r'[A-Za-z0-9_.@:-]{1,128}',value[k])
                   for k in ('subject','generation'))
            or not isinstance(value['project'],str) or not 1<=len(value['project'])<=512 or '\0' in value['project']):
        raise ValueError('INVALID_FACTORY_WRITE_AHEAD_BINDING')
    return value


def write_ahead(task,record):
    path=Path(task.directory)/WAL_NAME
    raw=json.dumps(record,sort_keys=True,separators=(',',':')).encode()
    if len(raw)>4096:raise ValueError('BOUNDED_FACTORY_WRITE_AHEAD_REQUIRED')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        offset=0
        while offset<len(raw):
            written=os.write(fd,raw[offset:])
            if type(written) is not int or not 0<written<=len(raw)-offset:
                raise OSError('FACTORY_WRITE_AHEAD_SHORT_WRITE_UNRESOLVED')
            offset+=written
        os.fsync(fd)
    finally:os.close(fd)
    sync_directory(task.directory)
    if read_wal(task.directory)!=record:raise ValueError('FACTORY_WRITE_AHEAD_READBACK_CHANGED')


def recover_allowance(task,saved):
    """Reconcile actual write-ahead bytes before any restarted admission."""
    task.a2a_factory_allowance=copy.deepcopy(saved)
    task.factory_budget_fault=getattr(task,'factory_budget_fault',False)
    try:
        wal=read_wal(task.directory)
        if wal is None and saved is None:return
        if wal is None or (saved is not None and saved!=wal):
            raise ValueError('FACTORY_WRITE_AHEAD_AND_TASK_DISAGREE')
        expected=dict(taskId=task.id,correlationId=task.correlation_id,subject=task.authenticated_subject,
            runtime=task.request['runtime'],project=task.request['project'],writes=task.request['writes'])
        if any(wal.get(k)!=v for k,v in expected.items()):
            raise ValueError('FOREIGN_RECOVERED_FACTORY_WRITE_AHEAD')
        task.a2a_factory_allowance=copy.deepcopy(wal)
        if saved is None:
            task.a2a_factory_allowance['status']='persistence-uncertain';task.factory_budget_fault=True
    except Exception:
        task.factory_budget_fault=True
        if isinstance(task.a2a_factory_allowance,dict):task.a2a_factory_allowance['status']='persistence-uncertain'
    if task.state=='interrupted' and task.a2a_factory_allowance is not None:
        # A restarted in-flight reservation is unresolved even if both copies
        # survived. Never silently reuse its remaining grant after a crash.
        task.factory_budget_fault=True


def reserve_launch(task,*,registry,admission,binding):
    fields={'subject','generation','taskId','correlationId','runtime','project','writes','promptSha256'}
    if (not isinstance(binding,dict) or set(binding)!=fields
            or not isinstance(admission,dict) or binding.get('subject')!=admission.get('subject')
            or binding.get('generation')!=admission.get('generation')
            or not isinstance(binding.get('generation'),str)
            or not re.fullmatch(r'[A-Za-z0-9_.@:-]{1,128}',binding['generation'])
            or binding.get('runtime') not in {'sdk','claude','deepagents'}
            or type(binding.get('writes')) is not bool
            or any(not re.fullmatch(r'[a-f0-9]{32}',str(binding.get(k))) for k in ('taskId','correlationId'))
            or not re.fullmatch(r'[a-f0-9]{64}',str(binding.get('promptSha256')))):
        raise ValueError('EXACT_FACTORY_ALLOWANCE_BINDING_REQUIRED')
    maximum=admission.get('modelStartsAllowed')
    if type(maximum) is not int or not 1<=maximum<=3:
        raise ValueError('FACTORY_LAUNCH_ALLOWANCE_EXHAUSTED')
    grant=hashlib.sha256(json.dumps(admission,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    with registry.lock:
        if getattr(registry,'factory_budget_faults',None):raise ValueError('FACTORY_GRANT_DURABILITY_UNRESOLVED')
        roots=list(registry.tasks.values())
        parents=[parent for parent in roots if getattr(parent,'active_a2a_child',None) is task]
        if registry.tasks.get(task.id) is not task and len(parents)!=1:
            raise ValueError('CANONICAL_FACTORY_TASK_OR_PARENT_REQUIRED')
        if len(parents)>1:raise ValueError('AMBIGUOUS_FACTORY_TASK_PARENT')
        locks=[task.persistence_lock]+([parents[0].persistence_lock] if parents else [])
        acquired=[]
        try:
            # Never wait under the Registry lock on a Task that might already
            # be waiting for Registry lookup. Busy admission causes no start.
            for lock in locks:
                if not lock.acquire(blocking=False):raise ValueError('FACTORY_WRITER_BUSY_NO_RESERVATION')
                acquired.append(lock)
            prompt=task.request.get('prompt')
            if (task.state!='running' or getattr(task,'a2a_factory_allowance',None) is not None
                    or task.authenticated_subject!=binding['subject']
                    or task.id!=binding['taskId'] or task.correlation_id!=binding['correlationId']
                    or type(task.request.get('writes')) is not bool
                    or any(task.request.get(k)!=binding[k] for k in ('runtime','project','writes'))
                    or not isinstance(prompt,str) or hashlib.sha256(prompt.encode()).hexdigest()!=binding['promptSha256']):
                raise ValueError('FACTORY_ALLOWANCE_TASK_FENCED_CHANGED_OR_ALREADY_RESERVED')
            seen={}
            for existing in roots:
                if getattr(existing,'factory_budget_fault',False):raise ValueError('FACTORY_GRANT_DURABILITY_UNRESOLVED')
                records=[getattr(existing,'a2a_factory_allowance',None)]
                records.extend(stage.get('factoryAllowance') for stage in getattr(existing,'a2a_stages',[]))
                child=getattr(existing,'active_a2a_child',None)
                if child is not None:records.append(getattr(child,'a2a_factory_allowance',None))
                # The durable file, not a Mock/in-memory save, is authoritative.
                wal=read_wal(existing.directory)
                allocation=getattr(existing,'a2a_factory_allowance',None)
                if wal!=allocation:raise ValueError('FACTORY_GRANT_DURABILITY_UNRESOLVED')
                for row in records:
                    if row is not None:
                        if not isinstance(row,dict) or not re.fullmatch(r'[a-f0-9]{32}',str(row.get('taskId'))):
                            raise ValueError('FACTORY_GRANT_DURABILITY_UNRESOLVED')
                        if read_wal(Path(existing.directory).parent/row['taskId'])!=row:
                            raise ValueError('FACTORY_GRANT_DURABILITY_UNRESOLVED')
                for row in records:
                    if row is None:continue
                    if (not isinstance(row,dict) or row.get('kind')!='DSH_FACTORY_LAUNCH_ALLOWANCE_V1'
                            or not re.fullmatch(r'[a-f0-9]{32}',str(row.get('reservationId')))
                            or not re.fullmatch(r'[a-f0-9]{64}',str(row.get('grantSha256')))
                            or row.get('status') not in {'reserved','persistence-uncertain'}):
                        raise ValueError('UNRESOLVED_OR_LEGACY_FACTORY_ALLOWANCE')
                    previous=seen.get(row['reservationId'])
                    if previous is not None and previous!=row:
                        raise ValueError('FACTORY_ALLOWANCE_COPIES_DISAGREE')
                    seen[row['reservationId']]=row
            if sum(row['grantSha256']==grant for row in seen.values())>=maximum:
                raise ValueError('FACTORY_LAUNCH_ALLOWANCE_EXHAUSTED')
            record=dict(kind='DSH_FACTORY_LAUNCH_ALLOWANCE_V1',reservationId=uuid.uuid4().hex,
                grantSha256=grant,status='reserved',**copy.deepcopy(binding))
            try:write_ahead(task,record)
            except BaseException:
                task.factory_budget_fault=True;task.state='interrupted'
                raise  # No lifecycle start without durable WAL+readback.
            parent=parents[0] if parents else None
            if parent is not None:
                stages=parent.a2a_stages
                if (not stages or stages[-1].get('stageId')!=task.id
                        or stages[-1].get('correlationId')!=task.correlation_id
                        or stages[-1].get('status')!='reserved' or stages[-1].get('factoryAllowance') is not None):
                    raise ValueError('EXACT_RESERVED_PARENT_STAGE_REQUIRED')
                # Parent retains consumed budget after active child is cleared.
                # Persist this copy first: a later child-save failure must not
                # restore an allowance for the next stage.
                stages[-1]['factoryAllowance']=copy.deepcopy(record)
                parent.save()
            task.a2a_factory_allowance=copy.deepcopy(record)
            try:task.save()
            except BaseException:
                task.a2a_factory_allowance['status']='persistence-uncertain';task.state='interrupted'
                raise
            return copy.deepcopy(record)
        finally:
            for lock in reversed(acquired):lock.release()
