"""Fixed, non-root Jupyter launch operation sent through the owner's terminal.

No user command, notebook path, host or environment is accepted. Existing
listeners are never stopped. A private flock/PID record deduplicates launches
even across gateway replacement; neither file enables startup after reboot.
"""
import fcntl
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import time

LOCK = '/tmp/.dsh-jupyter-demand.lock'
STATE = '/tmp/.dsh-jupyter-demand.pid'
ARGV = ['/opt/dsh/jupyter/bin/python', '/usr/local/bin/jupyter', 'lab']


def listening():
    with socket.socket() as s:
        s.settimeout(.25)
        return s.connect_ex(('127.0.0.1', 8888)) == 0


def protected_open(file, flags):
    fd = os.open(file, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    s = os.fstat(fd)
    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or s.st_uid != os.getuid() or s.st_mode & 0o077:
        os.close(fd)
        raise ValueError('UNSAFE_START_LOCK')
    return fd


def process_stamp(pid):
    if type(pid) is not int or pid <= 1:
        return None
    try:
        base = Path('/proc') / str(pid)
        if base.stat().st_uid != os.getuid():
            return None
        argv = (base / 'cmdline').read_bytes().rstrip(b'\0').split(b'\0')
        if argv != [x.encode() for x in ARGV]:
            return None
        # The comm field may contain spaces or parentheses; starttime is field 22.
        fields = (base / 'stat').read_text().rsplit(')', 1)[1].split()
        return fields[19]
    except (OSError, IndexError):
        return None


def read_state():
    try:
        fd = protected_open(STATE, os.O_RDONLY)
    except FileNotFoundError:
        return None
    try:
        data = os.read(fd, 1025)
        if len(data) > 1024:
            raise ValueError('UNSAFE_START_STATE')
        v = json.loads(data)
        if set(v) != {'pid', 'stamp'}:
            raise ValueError('UNSAFE_START_STATE')
        return v if process_stamp(v['pid']) == v['stamp'] else None
    finally:
        os.close(fd)


def write_state(value):
    # Existing state may be stale, but must still be a private regular file.
    fd = protected_open(STATE, os.O_WRONLY | os.O_CREAT)
    try:
        os.ftruncate(fd, 0)
        os.write(fd, json.dumps(value).encode())
        os.fsync(fd)
    finally:
        os.close(fd)


def ensure():
    if os.getuid() == 0:
        raise ValueError('NONROOT_RUNTIME_REQUIRED')
    fd = protected_open(LOCK, os.O_CREAT | os.O_RDWR)
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    return {'state': 'starting'}
                time.sleep(.1)
        if listening():
            return {'state': 'listening', 'reused': True}
        prior = read_state()
        child = None
        if prior is None:
            # Fixed, root-installed executable paths; no PATH or shell evaluation.
            for file in ARGV[:2]:
                s = os.stat(file)
                if not stat.S_ISREG(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
                    raise ValueError('UNTRUSTED_JUPYTER_EXECUTABLE')
            child = subprocess.Popen(ARGV, cwd='/workspace', stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     close_fds=True, start_new_session=True)
            stamp = process_stamp(child.pid)
            if stamp is None:
                return {'state': 'failed', 'code': 'JUPYTER_START_FAILED'}
            write_state({'pid': child.pid, 'stamp': stamp})
        while time.monotonic() < deadline:
            if listening():
                return {'state': 'listening', 'reused': prior is not None}
            if child is not None and child.poll() is not None:
                return {'state': 'failed', 'code': 'JUPYTER_START_FAILED'}
            time.sleep(.2)
        # Never kill a slow server, running kernel or another process on timeout.
        return {'state': 'starting'}
    finally:
        os.close(fd)


if __name__ == '__main__':
    nonce = sys.argv[1] if len(sys.argv) == 2 else ''
    if not re.fullmatch('[a-f0-9]{32}', nonce):
        raise SystemExit('Invalid launch request')
    try:
        result = ensure()
    except Exception:
        result = {'state': 'failed', 'code': 'JUPYTER_START_FAILED'}
    print('DSH_JUPYTER_START_' + nonce + ':' + json.dumps(result), flush=True)
