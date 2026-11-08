"""Query consumption by the EXISTING protected Task controller only.

The exporter invokes this injected command; it never becomes another Task
writer. The same Registry/Task locks and Task directory own the durable mark.
Any existing/partial intent or uncertain commit refuses a second DB query.
"""
import copy
import hashlib
import json
import os
from scripts.a2a_factory_budget import sync_directory

NAME='a2a-provider-export-consumed.json'


def consumption_record(query,*,generation,source):
    return dict(kind='DSH_PROVIDER_EXPORT_CONSUMPTION_V1',generation=generation,
        taskId=query['taskId'],captureOperationId=query['captureOperationId'],guardSha256=query['guardSha256'],
        query=copy.deepcopy(query),source=copy.deepcopy(source))


def canonical(record):return (json.dumps(record,sort_keys=True,separators=(',',':'))+'\n').encode()


class TaskControllerQueryConsumer:
    def __init__(self,*,registry,task_lookup,authorizer):
        if (not isinstance(getattr(registry,'tasks',None),dict) or not hasattr(getattr(registry,'lock',None),'acquire')
                or not callable(task_lookup) or not callable(getattr(authorizer,'validate_task',None))):
            raise ValueError('SOLE_TASK_WRITER_QUERY_CONSUMPTION_REQUIRED')
        self.registry,self.lookup,self.authorizer=registry,task_lookup,authorizer

    def __call__(self,query,*,generation,source):
        task=self.lookup(query['taskId'])
        if task is None:raise ValueError('UNKNOWN_PROVIDER_QUERY_TASK')
        with self.registry.lock:
            roots=list(self.registry.tasks.values())
            if (self.registry.tasks.get(task.id) is not task
                    and sum(getattr(parent,'active_a2a_child',None) is task for parent in roots)!=1):
                raise ValueError('CANONICAL_PROVIDER_QUERY_TASK_REQUIRED')
            if not task.persistence_lock.acquire(blocking=False):
                raise ValueError('PROVIDER_QUERY_WRITER_BUSY_NO_CONSUMPTION')
            try:
                self.authorizer.validate_task(task,query,generation=generation)
                worker=task.a2a_cli_worker;path=task.directory/NAME
                if (worker.get('providerExportConsumptionSha256') is not None
                        or worker.get('providerExportQueryOperationId') is not None
                        or path.exists() or path.is_symlink()):
                    raise ValueError('PROVIDER_EXPORT_QUERY_CONSUMED_OR_UNCERTAIN_NO_REQUERY')
                record=consumption_record(query,generation=generation,source=source);raw=canonical(record)
                if len(raw)>32768:raise ValueError('BOUNDED_QUERY_CONSUMPTION_REQUIRED')
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0),0o600)
                try:
                    offset=0
                    while offset<len(raw):
                        written=os.write(fd,raw[offset:])
                        if type(written) is not int or not 0<written<=len(raw)-offset:
                            raise OSError('PROVIDER_QUERY_CONSUMPTION_WRITE_UNRESOLVED')
                        offset+=written
                    os.fsync(fd)
                finally:os.close(fd)
                sync_directory(task.directory)
                if path.read_bytes()!=raw:raise ValueError('QUERY_CONSUMPTION_READBACK_CHANGED')
                digest=hashlib.sha256(raw).hexdigest()
                worker.update(providerExportQueryOperationId=query['captureOperationId'],
                    providerExportConsumptionSha256=digest,providerExportQueryStatus='consumed')
                task.save()  # Must complete BEFORE the exporter can SELECT.
                return dict(kind='DSH_PROVIDER_EXPORT_CONSUMED_V1',generation=generation,
                    taskId=task.id,captureOperationId=query['captureOperationId'],guardSha256=query['guardSha256'],
                    consumptionSha256=digest)
            finally:task.persistence_lock.release()
