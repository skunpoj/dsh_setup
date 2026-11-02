"""Pinned OpenShell RPC boundary; authenticated channel supplied by the server.

The bdb956f2 SDK convenience methods omit request_id. Use generated request
types explicitly so the existing Task reservation reaches native admission.
This module does not load credentials, choose policy, retry, or enable a backend.
"""
import json
import hashlib
import re
import time
import uuid

UPSTREAM_COMMIT = "bdb956f2cd65a635f1294fccf1d138d263bf650f"


def request_id(operation):
    if not isinstance(operation,str) or not re.fullmatch(r"[a-f0-9]{32}",operation):
        raise ValueError("INVALID_OPERATION_ID")
    value=uuid.UUID(hex=operation)
    if value.int==0:raise ValueError("ZERO_OPERATION_ID")
    return str(value)


class NativeOpenShellRPC:
    def __init__(self, stub, messages, datamodel, *, workspace, clock=time.time):
        if not isinstance(workspace,str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,17}[a-z0-9])?",workspace):
            raise ValueError("INVALID_NATIVE_WORKSPACE")
        self.stub,self.messages,self.datamodel=stub,messages,datamodel
        self.workspace,self.clock=workspace,clock

    def _scope(self):
        return self.datamodel.WorkspaceSelector(workspace=self.workspace)

    def _verified(self, response, binding_id, allocation_operation):
        try:
            metadata=response.sandbox.metadata
            valid=(metadata.name==self.name(binding_id) and metadata.workspace==self.workspace
                   and metadata.labels.get('dsh.example.com/binding')==binding_id
                   and metadata.labels.get('dsh.example.com/allocation')==allocation_operation
                   and isinstance(metadata.id,str)
                   and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',metadata.id))
        except (AttributeError,TypeError):valid=False
        if not valid:raise ValueError('NATIVE_ALLOCATION_IDENTITY_MISMATCH')
        return response

    @staticmethod
    def name(binding_id):
        if not isinstance(binding_id,str) or not re.fullmatch(r"[a-f0-9]{32}",binding_id):
            raise ValueError("INVALID_BINDING_ID")
        # Pinned gateway MAX_ROUTABLE_NAME_LEN is 19. Full identity stays in
        # the binding label; a short-name collision must fail, never be reused.
        return "dsh-"+hashlib.sha256(binding_id.encode()).hexdigest()[:15]

    def create(self, binding_id, operation_id, *, admitted_spec, expires_at):
        remaining=expires_at-self.clock()
        if not 0<remaining<=300:raise ValueError("EXPIRED_NATIVE_ALLOCATION")
        # admitted_spec is the protected server's exact immutable-image/policy
        # specification, not browser data or an upstream default specification.
        if admitted_spec is None:raise ValueError("ADMITTED_SPEC_REQUIRED")
        request=self.messages.CreateSandboxRequest(
            workspace_scope=self._scope(),name=self.name(binding_id),
            spec=admitted_spec,request_id=request_id(operation_id),
            labels={"dsh.example.com/binding":binding_id,"dsh.example.com/allocation":operation_id})
        return self._verified(self.stub.CreateSandbox(request,timeout=min(30,remaining)),binding_id,operation_id)

    def lookup(self, binding_id, allocation_operation):
        request_id(allocation_operation)
        request=self.messages.GetSandboxRequest(workspace_scope=self._scope(),name=self.name(binding_id))
        return self._verified(self.stub.GetSandbox(request,timeout=15),binding_id,allocation_operation)

    def execute(self, binding_id, operation_id, envelope):
        if envelope.get("bindingId")!=binding_id or envelope.get("operationId")!=operation_id:
            raise ValueError("NATIVE_EXECUTION_IDENTITY_MISMATCH")
        remaining=envelope["expiresAt"]-self.clock()
        if not 0<remaining<=300:raise ValueError("EXPIRED_NATIVE_EXECUTION")
        request=self.messages.ExecSandboxRequest(
            workspace_scope=self._scope(),sandbox=self.name(binding_id),
            command=["/usr/local/bin/dsh-openshell-worker"],
            stdin=json.dumps(envelope,separators=(",",":")).encode("utf-8"),
            no_login_shell=True,request_id=request_id(operation_id))
        request.execution_timeout.seconds=int(remaining)
        request.execution_timeout.nanos=int((remaining-int(remaining))*1_000_000_000)
        return self.stub.ExecSandbox(request,timeout=remaining)

    def stop(self, *_args, **_kwargs):
        # Pinned StopSandbox has no atomic expected-sandbox-ID condition.
        # A name-based stop is not an exact supervisor stop receipt.
        raise ValueError("EXACT_SUPERVISOR_STOP_REQUIRED")
