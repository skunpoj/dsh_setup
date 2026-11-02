"""Bound execution inside a native worker; no provider selection or retry.

Only the protected native transport may send the envelope. Identity is compared
with the protected assignment before creating an at-most-once reservation.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time


IDENTITY = ("subject", "generation", "taskId", "project", "bindingId", "workerUID", "podUID")


def validate(envelope, assigned, now):
    required=set(IDENTITY)|{"operationId","expiresAt","runtime","prompt","writes","correlationId"}
    if not isinstance(envelope,dict) or set(envelope)!=required:
        raise ValueError("INVALID_EXECUTION_ENVELOPE")
    if any(envelope[k]!=assigned.get(k) for k in IDENTITY):
        raise ValueError("FOREIGN_OR_STALE_EXECUTION")
    if not isinstance(envelope['podUID'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',envelope['podUID']):
        raise ValueError('INVALID_PHYSICAL_POD_IDENTITY')
    if not all(isinstance(envelope[k],str) and re.fullmatch(r"[a-f0-9]{32}",envelope[k])
               for k in ("operationId","correlationId")):
        raise ValueError("INVALID_OPERATION_ID")
    if type(envelope["expiresAt"]) not in (int,float) or not now<envelope["expiresAt"]<=now+300:
        raise ValueError("EXPIRED_EXECUTION")
    if envelope["expiresAt"]!=assigned.get("expiresAt"):
        raise ValueError("EXPIRY_CHANGED")
    if envelope["runtime"] not in {"sdk","claude","deepagents","kilo"} or type(envelope["writes"]) is not bool:
        raise ValueError("INVALID_RUNTIME_OR_MODE")
    if not isinstance(envelope["prompt"],str) or not 1<=len(envelope["prompt"])<=65536:
        raise ValueError("INVALID_PROMPT")
    return envelope


def reserve(root, envelope):
    # root is a fixed worker-private state directory, never taken from a request.
    root=Path(root)
    if root.is_symlink():raise ValueError("INVALID_STATE_ROOT")
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    # One execution per native binding, including different operation IDs.
    name=hashlib.sha256(envelope["bindingId"].encode()).hexdigest()+".json"
    with (root/name).open("x",encoding="utf-8") as stream:
        os.chmod(root/name,0o600)
        json.dump({k:envelope[k] for k in (*IDENTITY,"operationId","expiresAt","runtime","correlationId")},stream)
        stream.flush();os.fsync(stream.fileno())
    return root/name


def run(envelope, assigned, root, command_builder, *, clock=time.time, popen=subprocess.Popen, cancelled=lambda:False):
    validate(envelope,assigned,clock())
    project=Path("/workspace").resolve()
    cwd=(project/envelope["project"]).resolve()
    if cwd!=project and project not in cwd.parents:raise ValueError("PROJECT_ESCAPE")
    # Each native stage has its own reserved operation and one-start allowance.
    # Reusing the parent task ID would incorrectly block a legitimate handoff.
    command=command_builder(envelope["runtime"],envelope["prompt"],envelope["writes"],cwd,envelope["operationId"])
    reservation=reserve(root,envelope)
    env={k:v for k,v in os.environ.items() if k not in {
        "OPENAI_API_KEY","ANTHROPIC_API_KEY","GEMINI_API_KEY","GOOGLE_API_KEY",
        "AZDO_PAT","GH_TOKEN","GITHUB_TOKEN"}}
    env["DSH_CORRELATION_ID"]=envelope["correlationId"]
    env["DSH_UNATTENDED_TASK"]=envelope["operationId"]
    env["DSH_PARENT_TASK_ID"]=envelope["taskId"]
    process=None
    try:
        if clock()>=envelope["expiresAt"]:raise ValueError("EXPIRED_BEFORE_LAUNCH")
        if cancelled():return {"exitCode":143,"expired":False,"cancelled":True,"operationId":envelope["operationId"]}
        process=popen(command,cwd=str(cwd),env=env,start_new_session=True)
        while True:
            if cancelled():return {"exitCode":143,"expired":False,"cancelled":True,"operationId":envelope["operationId"]}
            remaining=envelope["expiresAt"]-clock()
            if remaining<=0:return {"exitCode":124,"expired":True,"operationId":envelope["operationId"]}
            try:
                code=process.wait(timeout=min(.2,remaining))
                return {"exitCode":code,"expired":False,"operationId":envelope["operationId"]}
            except subprocess.TimeoutExpired:
                continue
    finally:
        if process is not None:
            # Fence the entire process group, even if its leader already exited
            # while tool descendants remain. This module runs only on Linux.
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:pass
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        # Deliberately retain reservation after every outcome; no automatic replay.
