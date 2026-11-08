"""One Linux-only authenticated kubectl attach, with bounded private pipes.

The pinned official client handles Kubernetes streaming. Its explicit static
configuration lives only in a sealed Linux memfd, never disk, argv or env.
No credential discovery, exec auth plugin, retry, native Windows path or
remote-stop claim exists. Caller's before_attach must durably reserve ONE
attach in the existing Task journal before this helper may start.
"""
import base64
import hashlib
import json
import os
import selectors
import signal
import ssl
import stat
import subprocess
import threading
import time
import copy
from scripts.a2a_worker_identity import verify_pod,verify_terminal_worker

KUBECTL='/usr/local/bin/kubectl'
KUBECTL_SHA256='509ae171bac7ad3b98cc49f5594d6bc84900cf6860f155968d1059fde3be5286'
if os.name=='posix':
    import fcntl
else:
    fcntl=None


def verify_kubectl():
    fd=os.open(KUBECTL,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode & 0o022:
            raise ValueError('IMMUTABLE_PINNED_KUBECTL_REQUIRED')
        digest=hashlib.sha256()
        with os.fdopen(fd,'rb',closefd=False) as stream:
            while block:=stream.read(1048576):digest.update(block)
        if digest.hexdigest()!=KUBECTL_SHA256:raise ValueError('PINNED_KUBECTL_HASH_MISMATCH')
    finally:os.close(fd)


def static_kubeconfig(api):
    if not api.tls.check_hostname or api.tls.verify_mode!=ssl.CERT_REQUIRED:
        raise ValueError('VERIFIED_STREAM_TLS_REQUIRED')
    certificates=api.tls.get_ca_certs(binary_form=True)
    if not certificates:raise ValueError('EXPLICIT_STREAM_CA_BUNDLE_REQUIRED')
    pem=''.join(ssl.DER_cert_to_PEM_cert(value) for value in certificates).encode('ascii')
    if len(pem)>1048576:raise ValueError('STREAM_CA_BUNDLE_LIMIT')
    try:authorization=api.authorization()
    except Exception:
        raise RuntimeError('EXPLICIT_STREAM_AUTHORIZATION_UNAVAILABLE') from None
    if (not isinstance(authorization,str) or not authorization.startswith('Bearer ')
            or not 8<len(authorization)<=16384 or any(c in authorization for c in ('\r','\n','\0'))):
        raise ValueError('INVALID_INJECTED_STREAM_AUTHORIZATION')
    return {'apiVersion':'v1','kind':'Config','current-context':'owned-worker',
        'clusters':[{'name':'owned-worker','cluster':{'server':api.origin.geturl(),
            'certificate-authority-data':base64.b64encode(pem).decode('ascii')}}],
        'users':[{'name':'explicit-session','user':{'token':authorization[7:]}}],
        'contexts':[{'name':'owned-worker','context':{'cluster':'owned-worker',
            'user':'explicit-session','namespace':api.namespace}}]}


def write_frame_once(fd,data,abort,*,timeout=5,selector_factory=selectors.DefaultSelector,clock=time.monotonic):
    """Continue ONE frame at its next byte offset; never resend a prefix.

    Blocking/backpressured pipes cannot hold Task cancellation indefinitely.
    Any timeout/error fences the frame at the caller; no operation is retried.
    """
    if type(fd) is not int or fd<0 or not isinstance(data,bytes):
        raise ValueError('PRIVATE_PIPE_DESCRIPTOR_REQUIRED')
    if type(timeout) not in (int,float) or not 0<timeout<=5:
        raise ValueError('BOUNDED_PRIVATE_FRAME_TIMEOUT_REQUIRED')
    os.set_blocking(fd,False)
    selector=selector_factory()
    try:
        selector.register(fd,selectors.EVENT_WRITE)
        deadline=clock()+timeout;offset=0
        while offset<len(data):
            if abort.is_set():raise RuntimeError('PRIVATE_FRAME_CANCELLED')
            remaining=deadline-clock()
            if remaining<=0:raise TimeoutError('PRIVATE_FRAME_DELIVERY_TIMEOUT')
            if not selector.select(min(.05,remaining)):continue
            try:count=os.write(fd,data[offset:])
            except BlockingIOError:continue  # Zero bytes delivered; same frame/offset only.
            if count<=0:raise OSError('private pipe closed during frame')
            offset+=count
    finally:selector.close()


class WorkerStream:
    def __init__(self, *, api, expected_pod, pod_uid, before_attach, container='worker', terminal_context=None):
        if not callable(before_attach):raise ValueError('TASK_ATTACH_RESERVATION_REQUIRED')
        if container not in {'worker','model-guard'}:raise ValueError('FIXED_PRIVATE_STREAM_CONTAINER_REQUIRED')
        if container=='model-guard' and not isinstance(terminal_context,dict):
            raise ValueError('TERMINAL_WORKER_BINDING_REQUIRED_BEFORE_GUARD_DRAIN')
        self.api,self.expected,self.pod_uid=api,copy.deepcopy(expected_pod),pod_uid
        self.container=container;self.terminal_context=copy.deepcopy(terminal_context)
        self.before_attach=before_attach
        self.process=None;self.selector=None;self.started=False;self.closed=False;self.delivery_uncertain=False
        self.lock=threading.RLock();self.read_lock=threading.Lock()
        self.abort_send=threading.Event()
        self.buffer=bytearray();self.stderr_bytes=0

    def start(self):
        with self.lock:
            if self.started:raise ValueError('WORKER_STREAM_ALREADY_CONSUMED_NO_REATTACH')
            self.started=True
            if self.abort_send.is_set():raise ValueError('WORKER_STREAM_CANCELLED_BEFORE_START')
            if os.name!='posix' or not hasattr(os,'memfd_create') or fcntl is None:
                raise ValueError('LINUX_ONLY_WORKER_STREAM_REQUIRED')
            verify_kubectl()
            pod=self.api.read_pod(self.expected['metadata']['name'])
            if self.container=='worker':verify_pod(pod,self.expected,pod_uid=self.pod_uid,require_running=True)
            else:
                terminal=verify_terminal_worker(pod,self.expected,pod_uid=self.pod_uid,context=self.terminal_context)
                guard=next(value for value in pod['status']['containerStatuses'] if value['name']=='model-guard')
                if terminal['guardStopped'] or not guard.get('state',{}).get('running'):
                    raise ValueError('LIVE_GUARD_REQUIRED_FOR_ONE_DRAIN_ATTACH')
            if self.abort_send.is_set():raise ValueError('WORKER_STREAM_CANCELLED_BEFORE_ATTACH')
            self.before_attach()  # Must persist one-shot attach before subprocess/API stream.
            if self.abort_send.is_set():raise ValueError('WORKER_STREAM_CANCELLED_AFTER_RESERVATION')
            configuration=static_kubeconfig(self.api)
            raw=json.dumps(configuration,separators=(',',':')).encode()
            if len(raw)>2097152:raise ValueError('STREAM_CONFIGURATION_LIMIT')
            fd=os.memfd_create('dsh-worker-control',os.MFD_CLOEXEC|os.MFD_ALLOW_SEALING)
            try:
                with os.fdopen(fd,'wb',closefd=False) as stream:
                    stream.write(raw);stream.flush()
                os.lseek(fd,0,os.SEEK_SET)
                fcntl.fcntl(fd,fcntl.F_ADD_SEALS,fcntl.F_SEAL_WRITE|fcntl.F_SEAL_GROW|fcntl.F_SEAL_SHRINK|fcntl.F_SEAL_SEAL)
                command=[KUBECTL,'--kubeconfig=/proc/self/fd/'+str(fd),
                    '--namespace='+self.api.namespace,'--request-timeout=0s',
                    'attach',self.expected['metadata']['name'],'--container='+self.container,
                    '--stdin=true','--tty=false','--pod-running-timeout=5s','--quiet=true']
                if self.abort_send.is_set():raise ValueError('WORKER_STREAM_CANCELLED_BEFORE_HELPER')
                self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,bufsize=0,close_fds=True,pass_fds=(fd,),start_new_session=True,
                    env={'PATH':'/usr/local/bin:/usr/bin:/bin','LANG':'C.UTF-8','HOME':'/nonexistent'})
            finally:
                os.close(fd)
                # Only the explicitly delegated child retains its sealed memory
                # descriptor until it exits. No disk copy or parallel store.
            try:
                self.selector=selectors.DefaultSelector()
                self.selector.register(self.process.stdout,selectors.EVENT_READ,'stdout')
                self.selector.register(self.process.stderr,selectors.EVENT_READ,'stderr')
            except BaseException:
                self.close()
                raise

    def send_line(self,value):
        if not isinstance(value,str) or '\n' in value or '\r' in value or len(value.encode())>1048576:
            raise ValueError('BOUNDED_PRIVATE_WORKER_FRAME_REQUIRED')
        with self.lock:
            if not self.process or self.closed or self.delivery_uncertain or self.process.poll() is not None:
                raise ValueError('WORKER_STREAM_NOT_OPEN')
            data=(value+'\n').encode()
            # Same-frame byte continuation is not another request. A failed
            # delivery is uncertain and cannot be restarted as a new frame.
            try:
                write_frame_once(self.process.stdin.fileno(),data,self.abort_send)
            except Exception:
                self.delivery_uncertain=True
                self.process.stdin.close()
                raise RuntimeError('WORKER_STREAM_DELIVERY_UNCERTAIN_NO_RESEND') from None

    def receive_line(self, *, timeout=125):
        if type(timeout) not in (int,float) or not 0<timeout<=300:
            raise ValueError('BOUNDED_WORKER_STREAM_TIMEOUT_REQUIRED')
        with self.read_lock:
            if self.selector is None or self.closed:raise ValueError('WORKER_STREAM_NOT_OPEN')
            deadline=time.monotonic()+timeout
            while not self.closed:
                newline=self.buffer.find(b'\n')
                if newline>=0:
                    if newline>1048576:raise ValueError('WORKER_STREAM_OUTPUT_LIMIT')
                    raw=bytes(self.buffer[:newline]);del self.buffer[:newline+1]
                    return raw.decode('utf-8',errors='strict')
                if len(self.buffer)>1048576:raise ValueError('WORKER_STREAM_OUTPUT_LIMIT')
                if time.monotonic()>=deadline:raise TimeoutError('WORKER_STREAM_OBSERVATION_TIMEOUT')
                if not self.selector.get_map():raise EOFError('WORKER_STREAM_CLOSED_WITHOUT_COMPLETE_FRAME')
                for key,_ in self.selector.select(.05):
                    block=os.read(key.fileobj.fileno(),65536)
                    if not block:
                        self.selector.unregister(key.fileobj);continue
                    if key.data=='stdout':self.buffer.extend(block)
                    else:
                        self.stderr_bytes+=len(block)  # Never log/store raw stderr or authentication details.
                        if self.stderr_bytes>65536:raise ValueError('WORKER_STREAM_STDERR_LIMIT')
            raise EOFError('WORKER_STREAM_CLOSED')

    def close(self):
        self.abort_send.set()  # Wake a backpressured send BEFORE taking its lock.
        with self.lock:
            if self.closed:return
            self.closed=True
            process=self.process
            if process is not None:
                process.stdin.close()  # Worker source treats controller EOF as a fence, not a restart.
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    for signum in (signal.SIGTERM,signal.SIGKILL):
                        try:os.killpg(process.pid,signum)
                        except ProcessLookupError:pass
                        try:process.wait(timeout=1);break
                        except subprocess.TimeoutExpired:continue
                    if process.poll() is None:raise RuntimeError('LOCAL_STREAM_HELPER_STOP_UNVERIFIED')
            with self.read_lock:
                if process is not None:
                    process.stdout.close();process.stderr.close()
                if self.selector is not None:self.selector.close()
        # Closing this LOCAL helper is deliberately not remote descendant proof.
