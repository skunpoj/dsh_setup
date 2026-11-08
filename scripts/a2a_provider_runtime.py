"""Inert protected-controller exporter/capture assembly; never activation.

Owner supplies approved TLS contexts, finite policy and read-only spend store.
No server socket, thread, model call, secret discovery or new Task writer.
"""
from scripts.a2a_provider_exporter import RegistryQueryAuthorizer,ProviderMetadataExporter,TLSProviderMetadataQuery,handler_for
from scripts.a2a_provider_capture import TaskProviderCapture
from scripts.a2a_spend_store import LiteLLM193MetadataStore
from scripts.a2a_provider_query_journal import TaskControllerQueryConsumer
from scripts.a2a_worker_retirement import TaskWorkerRetirement,INTENT
from scripts.a2a_exporter_activation import ProtectedExporterActivation


class ProviderCaptureRuntime:
    def __init__(self,*,factory,origin,client_tls,exporter_admission,metadata_store,
                 source_observer,source_binding,connection_factory,clock):
        self.factory=factory
        self.clock=clock
        self.retirements=None
        if not isinstance(source_binding,dict) or source_binding.get('sourceCommit')!=factory.sdk.source_commit:
            raise ValueError('PROVIDER_RUNTIME_CONTROLLER_SOURCE_CHANGED')
        if type(metadata_store) is not LiteLLM193MetadataStore:
            raise ValueError('PINNED_READONLY_SPEND_STORE_IMPLEMENTATION_REQUIRED')
        authorizer=RegistryQueryAuthorizer(task_lookup=factory.lookup,generation=factory.sdk.generation)
        consumer=TaskControllerQueryConsumer(registry=factory.registry,task_lookup=factory.lookup,authorizer=authorizer)
        self.exporter=ProviderMetadataExporter(admission_reader=exporter_admission,authorize_query=authorizer,
            consume_query=consumer,metadata_store=metadata_store,source_observer=source_observer,source_binding=source_binding,clock=clock)
        self.query=TLSProviderMetadataQuery(origin=origin,namespace=factory.sdk.api.namespace,
            tls_context=client_tls,connection_factory=connection_factory)
        self.captures={runtime:TaskProviderCapture(controller=controller,generation=factory.sdk.generation,
            query_metadata=self.query,source_observer=source_observer,source_binding=source_binding)
            for runtime,controller in [('sdk',factory.sdk),('claude',factory.cli),('deepagents',factory.cli)]}
        self.handler=handler_for(self.exporter)

    def capture(self,task,binding):
        capture=self.captures.get(task.request.get('runtime'))
        if capture is None:raise ValueError('UNSUPPORTED_PROVIDER_CAPTURE_RUNTIME')
        # A reserved query is consumed even if its caller never saw a reply.
        # Recover retained bytes only; a missing/partial file must not cause
        # another query, including after controller reconstruction.
        with task.persistence_lock:
            reserved=getattr(task,'a2a_cli_worker',{}).get('providerCaptureOperationId')
        if reserved is not None:return capture.recover(task,binding)
        return capture(task,binding)

    def install(self):
        with self.factory.registry.lock:
            if getattr(self.factory,'provider_capture_runtime',None) is not None:
                raise ValueError('PROVIDER_RUNTIME_ALREADY_BOUND_NO_REPLACEMENT')
            self.factory.dependencies['providerCapture']=self.capture
            self.factory.provider_capture_runtime=self
        # Still no qualified flag, listener, Task admission or runtime exposure.

    def retire(self,task,binding):
        if self.retirements is None:
            raise ValueError('EXPLICIT_PROTECTED_RETIREMENT_BINDING_REQUIRED')
        capture=self.retirements.get(task.request.get('runtime'))
        if capture is None:raise ValueError('UNSUPPORTED_RETIREMENT_RUNTIME')
        retirement=TaskWorkerRetirement(registry=self.factory.registry,
            controller=capture.controller,capture=capture,
            admission_reader=lambda:self.retirement_admission(task,binding),clock=self.clock)
        # A complete or partial intent consumes deletion. Recovery may observe
        # it, but never replaces it or repeats a request with an unknown result.
        path=task.directory/INTENT
        if path.exists() or path.is_symlink():return retirement.recover(task,binding)
        return retirement.retire(task,binding)

    def install_retirement(self,*,admission_reader):
        if not callable(admission_reader):
            raise ValueError('EXPLICIT_TASK_SCOPED_CLEANUP_ADMISSION_REQUIRED')
        with self.factory.registry.lock:
            if getattr(self.factory,'provider_capture_runtime',None) is not self:
                raise ValueError('INSTALLED_CANONICAL_PROVIDER_RUNTIME_REQUIRED')
            if self.retirements is not None:
                raise ValueError('RETIREMENT_ALREADY_BOUND_NO_REPLACEMENT')
            # Admission is task-scoped and evaluated by each operation, never
            # manufactured from a previous model-start lease or credentials.
            self.retirement_admission=admission_reader
            self.retirements=dict(self.captures)
            self.factory.dependencies['retirement']=self.retire

    def install_activation(self,*,task,lease_reader,identity_observer,listener):
        with self.factory.registry.lock:
            if getattr(self.factory,'provider_capture_runtime',None) is not self:
                raise ValueError('INSTALLED_CANONICAL_PROVIDER_RUNTIME_REQUIRED')
            if getattr(self.factory,'exporter_activation',None) is not None:
                raise ValueError('EXPORTER_ACTIVATION_ALREADY_BOUND_NO_SECOND_LISTENER')
            activation=ProtectedExporterActivation(runtime=self,task=task,lease_reader=lease_reader,
                identity_observer=identity_observer,listener=listener)
            self.factory.exporter_activation=activation
            return activation  # Binding only; never invoke activate implicitly.
