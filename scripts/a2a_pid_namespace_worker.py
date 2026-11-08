"""One task's physical CLI supervisor, as PID 1 in a PRIVATE worker Pod.

Not a broker-local Popen fallback. This program requires root PID 1, a
non-root payload, no shared/host PID namespace and a controller-owned immutable
worker admission. Admission/provenance must be independently checked outside
this worker; this module never advertises qualified=True.
"""
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time
import uuid
import threading
import re
if __name__=='__main__':os.sys.path.insert(0,'/opt/dsh')
from scripts.a2a_worker_receipt import TerminationSink


MAX_OUTPUT = 262144


class ControlPipe:
    """Bounded, stoppable raw FD reader; no daemon buffered-stdin lock."""
    def __init__(self, fd):
        self.fd = fd
        self.buffer = bytearray()
        self.closing = threading.Event()
        self.selector = selectors.DefaultSelector()
        self.selector.register(fd, selectors.EVENT_READ)

    def readline(self, limit):
        while not self.closing.is_set():
            newline = self.buffer.find(b'\n')
            if newline >= 0:
                size = min(newline + 1, limit)
                value = bytes(self.buffer[:size]); del self.buffer[:size]
                return value
            if len(self.buffer) >= limit:
                value = bytes(self.buffer[:limit]); del self.buffer[:limit]
                return value
            if self.selector.select(0.05):
                block = os.read(self.fd, min(65536, limit-len(self.buffer)))
                if not block:
                    value = bytes(self.buffer);self.buffer.clear()
                    return value
                self.buffer.extend(block)
        return b''

    def stop(self):
        self.closing.set()

    def close(self):
        self.selector.close()


def unique_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('DUPLICATE_WORKER_FIELD')
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=pairs)


class WorkerCancellation:
    """One authenticated pipe's exact-scope stop request; no restart opcode."""
    def __init__(self, context):
        self.context = dict(context)
        self.event = threading.Event()
        self.lock = threading.Lock()
        self.operation_id = None
        self.error = None

    def request(self, value):
        with self.lock:
            if self.event.is_set():
                raise ValueError('WORKER_STOP_ALREADY_RESERVED')
            if (not isinstance(value, dict) or set(value) != {'kind','context','operationId'}
                    or value['kind'] != 'cancel' or value['context'] != self.context
                    or not isinstance(value['operationId'], str)
                    or not re.fullmatch(r'[a-f0-9]{32}', value['operationId'])):
                raise ValueError('FOREIGN_WORKER_STOP_REQUEST')
            self.operation_id = value['operationId']
            self.event.set()

    def disconnect(self, reason):
        with self.lock:
            if not self.event.is_set():
                self.error = reason
                self.event.set()

    def read_one(self, stream):
        try:
            raw = stream.readline(65537)
            if not raw:
                if getattr(stream, 'closing', threading.Event()).is_set():
                    return
                self.disconnect('WORKER_CONTROLLER_DISCONNECTED')
                return
            if len(raw) > 65536 or not raw.endswith(b'\n'):
                raise ValueError('WORKER_CONTROL_FRAME_LIMIT')
            self.request(unique_json(raw))
        except BaseException:
            self.disconnect('WORKER_CONTROL_FRAME_REFUSED')


def require_private_init():
    if os.name != 'posix' or os.getpid() != 1 or os.geteuid() != 0:
        raise ValueError('DEDICATED_ROOT_PID1_WORKER_REQUIRED')
    # A host PID namespace cannot have this Pod's supervisor as init. The
    # controller must ALSO reject hostPID/shareProcessNamespace in Pod admission.
    if Path('/proc/1/cmdline').read_bytes().split(b'\0')[0] != os.fsencode(os.sys.executable):
        raise ValueError('UNEXPECTED_NAMESPACE_INIT')
    status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    if status.get('NoNewPrivs', '').strip() != '1' or int(status.get('CapEff', '0').strip(), 16) != 0xe0:
        raise ValueError('WORKER_PRIVILEGE_BOUNDARY_REQUIRED')
    return os.stat('/proc/1/ns/pid').st_ino


def namespace_members():
    """All visible processes, including descendants that called setsid()."""
    return {int(p.name) for p in Path('/proc').iterdir()
            if p.name.isdecimal() and int(p.name) != 1}


def stop_namespace(*, timeout=5.0):
    require_private_init()
    if type(timeout) not in (int, float) or not 0 < timeout <= 5:
        raise ValueError('INVALID_WORKER_STOP_TIMEOUT')
    deadline = time.monotonic() + timeout
    while True:
        members = namespace_members()
        for pid in members:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        # PID 1 adopts and reaps orphaned descendants. No killpg-only proof.
        while True:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
                if pid == 0:
                    break
            except ChildProcessError:
                break
        if not namespace_members():
            return True
        if time.monotonic() >= deadline:
            raise TimeoutError('WORKER_DESCENDANTS_STILL_PRESENT')
        time.sleep(0.02)


def validate_worker_request(value):
    if not isinstance(value, dict) or set(value) != {
            'context', 'command', 'cwd', 'uid', 'gid', 'environment', 'timeoutSeconds'}:
        raise ValueError('INVALID_WORKER_REQUEST')
    context = value['context']
    if (not isinstance(context, dict) or set(context) != {
            'subject', 'stageId', 'correlationId', 'project', 'runtime', 'scopeUid'}
            or any(not isinstance(v, str) or not v or len(v) > 256 for v in context.values())
            or context['runtime'] not in {'claude', 'deepagents'}):
        raise ValueError('INVALID_WORKER_BINDING')
    command = value['command']
    if (not isinstance(command, list) or len(command) < 2
            or command[:2] != ['/usr/local/bin/dsh-unattended', context['runtime']]
            or any(not isinstance(arg, str) or '\0' in arg for arg in command)
            or sum(len(arg.encode()) for arg in command) > 1048576):
        raise ValueError('INVALID_WORKER_COMMAND')
    if command[2:8] != ['--task-id', context['stageId'], '--max-model-starts', '1', '--cwd', value['cwd']]:
        raise ValueError('WORKER_COMMAND_BINDING_MISMATCH')
    if command[8:11] != ['--external-guard-port', '4001', '--']:
        raise ValueError('WORKER_SEPARATE_GUARD_REQUIRED')
    # Never let the request choose root or inherit broker credentials.
    if value['uid'] != 10001 or type(value['uid']) is not int or value['gid'] != 10001 or type(value['gid']) is not int:
        raise ValueError('NONROOT_FIXED_PAYLOAD_ID_REQUIRED')
    env = value['environment']
    allowed = {'PATH', 'HOME', 'LANG', 'PYTHONPATH', 'DSH_CORRELATION_ID'}
    if (not isinstance(env, dict) or set(env) - allowed
            or any(not isinstance(v, str) or '\0' in v for v in env.values())
            or env.get('PATH') != '/opt/dsh/deepagents/bin:/usr/local/bin:/usr/bin:/bin'
            or env.get('HOME') != '/home/dsh'
            or env.get('DSH_CORRELATION_ID') != context['correlationId']
            or ('PYTHONPATH' in env and env['PYTHONPATH'] != '/opt/dsh')):
        raise ValueError('INVALID_WORKER_ENVIRONMENT')
    cwd = Path(value['cwd'])
    if (not cwd.is_absolute() or not cwd.is_relative_to('/workspace')
            or cwd.resolve(strict=True) != cwd):
        raise ValueError('WORKER_PROJECT_OUTSIDE_WORKSPACE')
    limit = value['timeoutSeconds']
    if type(limit) not in (int, float) or not 0 < limit <= 300:
        raise ValueError('INVALID_WORKER_DEADLINE')
    return context


def execute_once(value, *, cancellation=None):
    namespace_inode = require_private_init()
    context = validate_worker_request(value)
    pod_uid = Path('/etc/dsh-worker-identity/pod-uid').read_text(encoding='ascii').strip()
    if str(uuid.UUID(pod_uid)) != pod_uid or context['scopeUid'] != pod_uid:
        raise ValueError('WORKER_POD_UID_BINDING_MISMATCH')
    if cancellation is not None and cancellation.context != context:
        raise ValueError('FOREIGN_WORKER_CANCELLATION_SCOPE')
    if namespace_members():
        raise ValueError('WORKER_NOT_EMPTY_BEFORE_START')
    if cancellation is not None and cancellation.event.is_set():
        raise ValueError('WORKER_FENCED_BEFORE_PROCESS_START')
    # No shell, no inherited environment, no inherited broker descriptors.
    child = subprocess.Popen(value['command'], cwd=value['cwd'],
        env=dict(value['environment']), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True,
        start_new_session=True, user=value['uid'], group=value['gid'], extra_groups=[], umask=0o077)
    selector = None
    try:
        # From the instant a child exists, every setup failure must pass through
        # physical cleanup; selector construction/registration can also fail.
        selector = selectors.DefaultSelector()
        selector.register(child.stdout, selectors.EVENT_READ, 'stdout')
        selector.register(child.stderr, selectors.EVENT_READ, 'stderr')
        output = bytearray()
        total = 0
        deadline = time.monotonic() + value['timeoutSeconds']
        exited = False
        while selector.get_map():
            if cancellation is not None and cancellation.event.is_set():
                stop_namespace()
                if cancellation.error is not None:
                    raise ValueError(cancellation.error)
                return {**context, 'exitCode': None, 'output': '', 'cancelled': True,
                    'operationId': cancellation.operation_id, 'stopped': True,
                    'processExitVerified': True, 'descendantAbsenceVerified': True,
                    'pidNamespaceInode': namespace_inode}
            if time.monotonic() >= deadline:
                raise TimeoutError('WORKER_TASK_DEADLINE')
            for key, _ in selector.select(0.05):
                block = os.read(key.fileobj.fileno(), 65536)
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                total += len(block)
                if total > MAX_OUTPUT:
                    raise ValueError('WORKER_OUTPUT_LIMIT')
                if key.data == 'stdout':
                    output.extend(block)
            if child.poll() is not None:
                exited = True
                # A descendant can retain pipes after its leader has exited.
                # Kill/reap the namespace, then drain finite already-buffered bytes.
                stop_namespace()
        exit_code = child.wait(timeout=max(0.01, deadline-time.monotonic()))
        exited = True
        stop_namespace()
        if cancellation is not None and cancellation.event.is_set():
            # A late cancellation cannot be reported as successful completion.
            if cancellation.error is not None:
                raise ValueError(cancellation.error)
            return {**context, 'exitCode': exit_code, 'output': '', 'cancelled': True,
                'operationId': cancellation.operation_id, 'stopped': True,
                'processExitVerified': True, 'descendantAbsenceVerified': True,
                'pidNamespaceInode': namespace_inode}
        if os.stat('/proc/1/ns/pid').st_ino != namespace_inode:
            raise ValueError('WORKER_NAMESPACE_IDENTITY_CHANGED')
        return {**context, 'exitCode': exit_code, 'output': output.decode('utf-8', errors='strict'),
            'stopped': True, 'processExitVerified': exited,
            'descendantAbsenceVerified': not namespace_members(), 'pidNamespaceInode': namespace_inode}
    finally:
        # On error, cleanup failure remains an error; it cannot become a receipt.
        try:
            stop_namespace()
        finally:
            try:
                if selector is not None:selector.close()
            finally:
                try:child.stdout.close()
                finally:child.stderr.close()


def main():
    require_private_init()
    sink = TerminationSink()  # Protect evidence before any payload can run.
    # One bounded input and one execution for the lifetime of this Pod.
    stream = ControlPipe(os.sys.stdin.fileno())
    reader = None
    try:
        raw = stream.readline(1048577)
        if len(raw) > 1048576 or not raw.endswith(b'\n'):
            raise ValueError('WORKER_INPUT_LIMIT')
        request = unique_json(raw)
        context = validate_worker_request(request)
        cancellation = WorkerCancellation(context)
        reader = threading.Thread(target=cancellation.read_one, args=(stream,))
        reader.start()
        result = execute_once(request, cancellation=cancellation)
        sink.write(result)
    finally:
        try:
            stream.stop()
            if reader is not None:
                reader.join(timeout=1)
                if reader.is_alive():
                    raise RuntimeError('WORKER_CONTROL_READER_NOT_STOPPED')
        finally:
            try:stream.close()
            finally:sink.close()
    os.sys.stdout.write(json.dumps(result, separators=(',', ':')) + '\n')
    os.sys.stdout.flush()


if __name__ == '__main__':
    main()
