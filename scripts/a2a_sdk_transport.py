"""SDKControlPeer transport over an already admitted private worker stream.

Inert composition only. Protected factory supplies exact stream and existing
Task journal callbacks; this module grants no qualification or execution lease.
"""
import base64
import copy
import json
import re
import threading
from scripts.a2a_sdk_worker import prepare_request
from scripts.a2a_worker_receipt import terminal_projection
from scripts.official_sdk_control_peer import SDKFrameCodec,MAX_FRAME
from scripts.official_sdk_package_admission import unique_json


class SDKWorkerTransport:
    def __init__(self,*,stream,context,timeout_seconds,before_start,before_cancel,banking=False):
        if not callable(before_start) or not callable(before_cancel):
            raise ValueError('EXISTING_SDK_TASK_JOURNAL_CALLBACKS_REQUIRED')
        if type(banking) is not bool:raise ValueError('EXPLICIT_SDK_TRANSPORT_MODE_REQUIRED')
        self.banking=banking
        if type(timeout_seconds) not in (int,float) or not 0<timeout_seconds<=(300 if banking else 120):
            raise ValueError('BOUNDED_SDK_TRANSPORT_DEADLINE_REQUIRED')
        self.stream=stream;self.context=copy.deepcopy(context);self.timeout=timeout_seconds
        self.before_start=before_start;self.before_cancel=before_cancel
        self.lock=threading.RLock();self.write_lock=threading.Lock()
        self.started=False;self.closed=False;self.failed=False;self.delivered=False
        self.start_done=threading.Event();self.cancel_operation=None;self.terminal=None
        self.outbound=None;self.inbound=None

    def start(self,bootstrap):
        with self.lock:
            if self.started or self.closed or self.failed:raise ValueError('SDK_TRANSPORT_START_CONSUMED')
            self.started=True
        try:
            request=dict(context=self.context,bootstrap=bootstrap,timeoutSeconds=self.timeout)
            _,boot,_=prepare_request(request,pod_uid=self.context['scopeUid'],banking=self.banking)
            key=base64.b64decode(boot['key'],validate=True)
            self.outbound=SDKFrameCodec(key,boot['binding']);self.inbound=SDKFrameCodec(key,boot['binding'])
            self.before_start()  # Existing native Task launch reservation must be durable.
            with self.lock:
                if self.closed or self.cancel_operation is not None:raise ValueError('SDK_TRANSPORT_FENCED_BEFORE_ATTACH')
            self.stream.start()
            with self.lock:
                if self.closed or self.cancel_operation is not None:raise ValueError('SDK_TRANSPORT_FENCED_BEFORE_BOOTSTRAP')
            self.stream.send_line(json.dumps(dict(request,bootstrap=boot),separators=(',',':')))
            self.delivered=True
        except BaseException:
            self.failed=True;self.close();raise
        finally:self.start_done.set()

    def send(self,frame):
        with self.write_lock:
            try:
                if (self.closed or self.failed or self.terminal is not None
                        or self.cancel_operation is not None or not self.delivered):
                    raise ValueError('SDK_TRANSPORT_NOT_OPEN')
                if not isinstance(frame,str) or '\n' in frame or '\r' in frame or len(frame.encode())>MAX_FRAME:
                    raise ValueError('BOUNDED_SDK_TRANSPORT_FRAME_REQUIRED')
                self.outbound.decode(frame)  # Check exact MAC/binding/sequence before forwarding.
                self.stream.send_line(json.dumps(dict(kind='sdk-frame',context=self.context,frame=frame),separators=(',',':')))
            except BaseException:
                self.failed=True
                raise

    def receive(self):
        if self.closed or self.failed or not self.delivered:raise ValueError('SDK_TRANSPORT_NOT_OPEN')
        try:
            raw=self.stream.receive_line(timeout=min(125,self.timeout+5))
            value=unique_json(raw.encode())
            if (isinstance(value,dict) and set(value)=={'kind','context','frame'}
                    and value['kind']=='sdk-frame' and value['context']==self.context
                    and isinstance(value['frame'],str)):
                self.inbound.decode(value['frame'])
                return value['frame']
            if isinstance(value,dict) and set(value)=={'kind','receipt'} and value['kind']=='terminal':
                projection=terminal_projection(value['receipt'])
                if any(projection.get(key)!=item for key,item in self.context.items()):
                    raise ValueError('FOREIGN_SDK_WORKER_TERMINAL_FRAME')
                # Publish terminal observation at the SAME ordering boundary
                # as cancel delivery. Never publish it halfway through a
                # cancel write and then claim that later write was admitted.
                with self.write_lock:
                    with self.lock:self.terminal=copy.deepcopy(value['receipt'])
                raise EOFError('SDK_WORKER_TERMINAL_REQUIRES_ACTUAL_POD_OBSERVATION')
            raise ValueError('FOREIGN_SDK_WORKER_FRAME')
        except BaseException:
            self.failed=True
            raise

    def cancel_once(self,operation_id):
        if not re.fullmatch(r'[a-f0-9]{32}',str(operation_id)):
            raise ValueError('EXACT_SDK_STOP_OPERATION_REQUIRED')
        with self.lock:
            if self.terminal is not None:
                raise ValueError('SDK_TERMINAL_OBSERVED_RECONCILE_ONLY')
            if self.cancel_operation is not None:raise ValueError('SDK_STOP_ALREADY_CONSUMED_NO_RESEND')
            self.cancel_operation=operation_id
        try:self.before_cancel(operation_id)  # Verify the existing native stop reservation.
        except BaseException:
            self.close()  # EOF fences the worker, but is not a successful stop receipt.
            raise
        if not self.start_done.wait(5) or not self.delivered or self.closed:
            self.close();raise ValueError('SDK_BOOTSTRAP_UNCERTAIN_STOP_NOT_VERIFIED')
        with self.write_lock:
            with self.lock:
                if self.terminal is not None:
                    raise ValueError('SDK_TERMINAL_OBSERVED_RECONCILE_ONLY')
            self.stream.send_line(json.dumps(dict(kind='cancel',context=self.context,
                operationId=operation_id),separators=(',',':')))
        return {'operationId':operation_id,'stopFrameDelivered':True,'processExitVerified':False}

    def close(self):
        with self.lock:
            if self.closed:return
            self.closed=True
        self.stream.close()  # Local pipe close is deliberately NOT remote-stop proof.
