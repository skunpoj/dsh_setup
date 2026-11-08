"""Small physical CLI stop evidence for the worker's termination message.

Only PID1/root writes this file, protected BEFORE the unprivileged client is
started. No prompt, output text, environment, credential or request body is
copied into the termination message. A receipt is still checked against actual
Pod UID/image/exit state by the protected controller before acceptance.
"""
import hashlib
import json
import os
import re
import stat
import uuid

FIELDS={'subject','stageId','correlationId','project','runtime','scopeUid'}


def terminal_projection(receipt):
    if not isinstance(receipt,dict):raise ValueError('INVALID_PHYSICAL_WORKER_RECEIPT')
    if (any(not isinstance(receipt.get(k),str) or not receipt[k] or len(receipt[k])>256 for k in FIELDS)
            or receipt['runtime'] not in {'claude','deepagents','sdk'}
            or not re.fullmatch(r'[a-f0-9]{32}',receipt['stageId'])
            or not re.fullmatch(r'[a-f0-9]{32}',receipt['correlationId'])
            or str(uuid.UUID(receipt['scopeUid']))!=receipt['scopeUid']
            or any(receipt.get(k) is not True for k in ('stopped','processExitVerified','descendantAbsenceVerified'))
            or type(receipt.get('pidNamespaceInode')) is not int
            or not 0<receipt['pidNamespaceInode']<2**64
            or not isinstance(receipt.get('output'),str) or len(receipt['output'].encode())>262144
            or receipt.get('exitCode') is not None and type(receipt['exitCode']) is not int):
        raise ValueError('UNVERIFIED_PHYSICAL_WORKER_RECEIPT')
    value={k:receipt[k] for k in FIELDS}
    value.update(kind='DSH_CLI_WORKER_TERMINAL_V1',stopped=True,processExitVerified=True,
        descendantAbsenceVerified=True,pidNamespaceInode=receipt['pidNamespaceInode'],
        exitCode=receipt.get('exitCode'),outputSha256=hashlib.sha256(receipt['output'].encode()).hexdigest())
    if receipt.get('cancelled') is True:
        if not re.fullmatch(r'[a-f0-9]{32}',str(receipt.get('operationId',''))):
            raise ValueError('EXACT_WORKER_STOP_OPERATION_REQUIRED')
        value.update(cancelled=True,operationId=receipt['operationId'])
        if receipt.get('neverStarted') is True:value['neverStarted']=True
    elif receipt.get('exitCode') is None:
        raise ValueError('NATIVE_EXIT_OR_EXACT_CANCELLATION_REQUIRED')
    raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
    if len(raw)>4096:raise ValueError('PHYSICAL_WORKER_RECEIPT_LIMIT')
    return value


def decode_projection(message):
    if not isinstance(message,str) or not message or len(message.encode())>4096:
        raise ValueError('BOUNDED_TERMINATION_MESSAGE_REQUIRED')
    def pairs(items):
        value={}
        for key,item in items:
            if key in value:raise ValueError('DUPLICATE_TERMINATION_FIELD')
            value[key]=item
        return value
    value=json.loads(message,object_pairs_hook=pairs)
    if not isinstance(value,dict) or not re.fullmatch(r'[a-f0-9]{64}',str(value.get('outputSha256',''))):
        raise ValueError('INVALID_TERMINATION_OUTPUT_HASH')
    # Reuse the exact physical metadata validation, without inventing a lost
    # result. Its original output hash is retained; output availability is a
    # separate observation and is never inferred from this receipt alone.
    expected=terminal_projection({**value,'output':''})
    expected['outputSha256']=value['outputSha256']
    if json.dumps(value,sort_keys=True,separators=(',',':'))!=json.dumps(expected,sort_keys=True,separators=(',',':')):
        raise ValueError('UNADMITTED_TERMINATION_MESSAGE_FIELDS')
    return value


class TerminationSink:
    def __init__(self):
        if os.name!='posix' or os.getpid()!=1 or os.geteuid()!=0:
            raise ValueError('PRIVATE_WORKER_INIT_REQUIRED')
        fd=os.open('/dev/termination-log',os.O_WRONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=0:
                raise ValueError('ROOT_OWNED_TERMINATION_SINK_REQUIRED')
            os.fchmod(fd,0o600)  # Payload UID10001 cannot forge physical evidence.
        except BaseException:
            os.close(fd);raise
        self.fd=fd;self.written=False

    def write(self,receipt):
        if self.written:raise ValueError('PHYSICAL_RECEIPT_ALREADY_WRITTEN')
        value=terminal_projection(receipt)
        raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
        self.written=True
        os.ftruncate(self.fd,0);os.lseek(self.fd,0,os.SEEK_SET)
        offset=0
        while offset<len(raw):
            count=os.write(self.fd,raw[offset:])
            if count<=0:raise OSError('physical receipt write incomplete')
            offset+=count
        os.fsync(self.fd)

    def close(self):
        if self.fd is not None:
            os.close(self.fd);self.fd=None
