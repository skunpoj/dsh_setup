"""Protected server admission; absent configuration never enables OpenShell.

The Production receipt is an independently reviewed, root-protected artifact.
This loader validates its exact binding and evidence bytes; it does not replace
real-image qualification or turn a source test into runtime acceptance.
"""
import hashlib
import json
import os
from pathlib import PurePosixPath
import re
import stat
import time
import types
from scripts.openshell_broker_transport import NativeBrokerTransport
from scripts.openshell_task_binding import BrokerOpenShellService

ROOTS=('/opt/dsh/','/etc/dsh-native-admission/')
ROLES={'gateway','sandbox','supervisor','worker','controller'}


def protected_path(value):
    if (not isinstance(value,str) or not value.startswith(ROOTS)
            or '..' in PurePosixPath(value).parts or '\\' in value):
        raise ValueError('UNPROTECTED_ADMISSION_PATH')
    return value


def digest(value):
    return isinstance(value,str) and re.fullmatch(r'[a-f0-9]{64}',value) and value!='0'*64


def read_protected(path):
    protected_path(path)
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode & 0o022:
            raise ValueError('UNPROTECTED_ADMISSION_FILE')
        with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(1048577)
        if len(raw)>1048576:raise ValueError('ADMISSION_FILE_TOO_LARGE')
        return raw
    finally:os.close(fd)


def load_factory(path,source):
    module=types.ModuleType('dsh_admitted_openshell_transport')
    module.__file__=path
    exec(compile(source,path,'exec'),module.__dict__)
    factory=getattr(module,'build_transport',None)
    if not callable(factory):raise ValueError('NATIVE_TRANSPORT_FACTORY_REQUIRED')
    return factory


def checked_evidence(binding,reader):
    if not isinstance(binding,dict) or set(binding)!={'path','sha256'} or not digest(binding['sha256']):
        raise ValueError('INVALID_NATIVE_EVIDENCE_BINDING')
    raw=reader(protected_path(binding['path']))
    if not raw or hashlib.sha256(raw).hexdigest()!=binding['sha256']:
        raise ValueError('NATIVE_EVIDENCE_HASH_MISMATCH')
    return raw


def check_acceptance(config,reader):
    receipt=json.loads(checked_evidence(config['acceptance'],reader))
    if (receipt.get('kind')!='DSH_OPENSHELL_NATIVE25_ACCEPTANCE_V1'
            or receipt.get('imageLock')!=config['imageLock']
            or receipt.get('policySha256')!=config['policySha256']
            or receipt.get('transportSha256')!=config['transportSha256']
            or receipt.get('sourceCommit')!=config['sourceCommit']
            or not isinstance(receipt.get('acceptedBy'),str) or not receipt['acceptedBy'].strip()):
        raise ValueError('NATIVE_ACCEPTANCE_IDENTITY_MISMATCH')
    gates=receipt.get('gates',[])
    if (len(gates)!=25 or {g.get('id') for g in gates}!={'T%02d'%i for i in range(1,26)}
            or any(g.get('result')!='PASSED' for g in gates)):
        raise ValueError('NATIVE25_ACCEPTANCE_INCOMPLETE')
    paths=[]
    for gate in gates:
        checked_evidence(gate['evidence'],reader);paths.append(gate['evidence']['path'])
    if len(set(paths))!=25:raise ValueError('NATIVE_GATE_EVIDENCE_REUSED')
    rollback=receipt.get('rollback',{})
    if rollback.get('result')!='PASSED':raise ValueError('NATIVE_ROLLBACK_INCOMPLETE')
    checked_evidence(rollback['evidence'],reader)
    if rollback['evidence']['path'] in paths:raise ValueError('NATIVE_ROLLBACK_EVIDENCE_REUSED')


def configure(server,registry,path,*,clock=time.time,reader=read_protected,factory_loader=load_factory):
    if not path:return False
    config=json.loads(reader(protected_path(path)))
    required={'kind','mode','subject','generation','expiresAt','namespace','sourceCommit',
              'imageLock','policySha256','transportModule','transportSha256','acceptance'}
    if not isinstance(config,dict) or set(config)!=required or config['kind']!='DSH_OPENSHELL_SERVER_ADMISSION_V1':
        raise ValueError('INVALID_NATIVE_ADMISSION')
    if config['mode'] not in {'qualification','production'}:raise ValueError('INVALID_NATIVE_MODE')
    if type(config['expiresAt']) not in (int,float):raise ValueError('INVALID_NATIVE_ADMISSION_EXPIRY')
    remaining=config['expiresAt']-clock()
    if not 0<remaining<=3600:raise ValueError('NATIVE_ADMISSION_EXPIRED_OR_TOO_LONG')
    expected_namespace='dsh-openshell-test-20261028' if config['mode']=='qualification' else 'dsh-openshell'
    if config['namespace']!=expected_namespace:raise ValueError('INVALID_NATIVE_NAMESPACE')
    if (not isinstance(config['sourceCommit'],str) or not re.fullmatch(r'[a-f0-9]{40}',config['sourceCommit'])
            or config['sourceCommit']=='0'*40):
        raise ValueError('INVALID_NATIVE_SOURCE_PIN')
    images=config['imageLock']
    if (not isinstance(images,dict) or set(images)!=ROLES
            or any(not isinstance(v,str) or not v.startswith('sha256:') or not digest(v[7:]) for v in images.values())
            or not digest(config['policySha256']) or not digest(config['transportSha256'])):
        raise ValueError('INVALID_NATIVE_IMAGE_OR_SOURCE_LOCK')
    if config['mode']=='production':check_acceptance(config,reader)
    elif config['acceptance'] is not None:raise ValueError('QUALIFICATION_CANNOT_CLAIM_PRODUCTION_ACCEPTANCE')
    module_path=protected_path(config['transportModule'])
    if not module_path.startswith('/opt/dsh/scripts/') or not module_path.endswith('.py'):
        raise ValueError('INVALID_NATIVE_TRANSPORT_MODULE')
    source=reader(module_path)
    if hashlib.sha256(source).hexdigest()!=config['transportSha256']:raise ValueError('NATIVE_TRANSPORT_HASH_MISMATCH')
    # Validate the assigned owner before loading any native implementation.
    for key in ('subject','generation'):
        if not isinstance(config[key],str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',config[key]):
            raise ValueError('INVALID_SERVER_IDENTITY')
    factory=factory_loader(module_path,source)
    transport=factory(registry=registry,admission=dict(config))
    if not isinstance(transport,NativeBrokerTransport):raise ValueError('UNAPPROVED_NATIVE_TRANSPORT')
    service=BrokerOpenShellService(registry,config['subject'],config['generation'],transport,
        qualified=True,admission_expires_at=config['expiresAt'])
    # Recovery may stop an old owned generation, but never allocates or replays.
    service.recover_pending()
    server.openshell_service=service
    return True
