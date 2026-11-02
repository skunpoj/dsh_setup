"""Native worker stdin entry point. No credential discovery or backend fallback."""
import json
import os
import re
from pathlib import Path
import stat
import sys
import signal
import threading
from scripts.agent_runtime_commands import command_for
from scripts.openshell_worker_execution import run

ASSIGNMENT=Path('/run/dsh-openshell/assignment.json')
POD_IDENTITY=Path('/run/dsh-openshell/pod-uid')
STATE=Path('/state/openshell-executions')
MAX_INPUT=131072


def read_protected(path, limit):
    flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)
    fd=os.open(path,flags)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode & 0o022:
            raise ValueError('UNPROTECTED_WORKER_ASSIGNMENT')
        with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(limit+1)
        if len(raw)>limit:raise ValueError('WORKER_ASSIGNMENT_TOO_LARGE')
        return raw
    finally:os.close(fd)


def read_assignment(path=ASSIGNMENT, *, pod_identity=POD_IDENTITY):
    # The admitted operator must mount the actual Kubernetes metadata.uid as a
    # root-owned, non-writable regular file. Environment variables and browser
    # payloads are not a source of physical identity. Missing mount fails closed.
    actual=read_protected(pod_identity,129).decode('ascii').strip()
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',actual):
        raise ValueError('INVALID_PHYSICAL_POD_IDENTITY')
    assigned=json.loads(read_protected(path,8192))
    if not isinstance(assigned,dict) or assigned.get('podUID')!=actual:
        raise ValueError('ASSIGNMENT_PHYSICAL_POD_MISMATCH')
    return assigned


def main(stdin=None, *, assignment=ASSIGNMENT, state=STATE, runner=run):
    stdin=stdin or sys.stdin.buffer
    stop=threading.Event();previous={}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM,signal.SIGINT):
            previous[sig]=signal.getsignal(sig)
            signal.signal(sig,lambda *_:stop.set())
    try:
        raw=stdin.read(MAX_INPUT+1)
        if len(raw)>MAX_INPUT:raise ValueError('EXECUTION_ENVELOPE_TOO_LARGE')
        envelope=json.loads(raw)
        assigned=read_assignment(assignment)
        result=runner(envelope,assigned,state,command_for,cancelled=stop.is_set)
        return result['exitCode'] if type(result.get('exitCode')) is int and 0<=result['exitCode']<=255 else 70
    except Exception as error:
        # Exception values can contain prompt/path/provider data; emit type only.
        print('Native worker refused: '+type(error).__name__,file=sys.stderr)
        return 70
    finally:
        for sig,handler in previous.items():signal.signal(sig,handler)
