"""CLI lifecycle over the existing Task-owned physical worker controller.

No qualification/admission flag, second writer, default credential, local
subprocess fallback or retry. Protected supervisor admission and complete
guard/provider accounting/retirement remain required owner integrations.
"""
import time
from scripts.a2a_worker_stream import WorkerStream
from scripts.a2a_private_worker_pod import worker_pod_name
from scripts.official_sdk_package_admission import unique_json


class CLIControllerLifecycle:
    def __init__(self,*,controller,task_lookup,stream_factory=WorkerStream,observation_timeout=2):
        if not callable(task_lookup) or not callable(stream_factory):
            raise ValueError('EXISTING_TASK_LOOKUP_AND_PRIVATE_STREAM_REQUIRED')
        if type(observation_timeout) not in (int,float) or not 0<observation_timeout<=2:
            raise ValueError('BOUNDED_CLI_STOP_OBSERVATION_REQUIRED')
        self.controller=controller;self.task_lookup=task_lookup
        self.stream_factory=stream_factory;self.observation_timeout=observation_timeout

    def _task(self,context,*,stop=False):
        if not isinstance(context,dict):raise ValueError('EXACT_CLI_CONTEXT_REQUIRED')
        task=self.task_lookup(context.get('stageId'))
        if task is None:raise ValueError('EXISTING_CLI_TASK_REQUIRED')
        expected=dict(subject=self.controller.subject,stageId=task.id,correlationId=task.correlation_id,
                      project=task.request['project'],runtime=task.request['runtime'])
        if stop:
            cancel=getattr(task,'a2a_cli_cancel',None)
            if not isinstance(cancel,dict) or cancel.get('status')!='reserved':
                raise ValueError('DURABLE_CLI_STOP_RESERVATION_REQUIRED')
            expected['operationId']=cancel.get('operationId')
        if (task.authenticated_subject!=self.controller.subject or context!=expected
                or task.request['runtime'] not in {'claude','deepagents'}
                or task.request.get('backend')!='private'
                or task.a2a_cli_context!={k:v for k,v in expected.items() if k!='operationId'}):
            raise ValueError('FOREIGN_CLI_LIFECYCLE_BINDING')
        return task

    def _observe(self,callback):
        deadline=time.monotonic()+self.observation_timeout
        while True:
            try:return callback()
            except ValueError as error:
                if str(error)!='WORKER_INIT_EXIT_UNVERIFIED' or time.monotonic()>=deadline:raise
                time.sleep(.025)  # Readback only, never a new attach/stop/start.

    def execute_once(self,context,command,project):
        task=self._task(context)
        with task.persistence_lock:
            if task.state!='running':raise ValueError('CLI_TASK_FENCED_BEFORE_PHYSICAL_LAUNCH')
        self.controller.prepare_cli(task,command,project)
        stream=self.controller.open_cli_stream(task,stream_factory=self.stream_factory)
        # Preserve the same controller-owned handle after observation errors.
        # Never reattach/restart to recover a missing model result.
        raw=stream.receive_line(timeout=125)
        result=unique_json(raw.encode())
        proof=self._observe(lambda:self.controller.observe_terminal(task,stream_receipt=result))
        self.controller.retain_terminal(task,stream_receipt=result)
        if proof.get('outputAvailable') is not True:
            raise ValueError('PHYSICAL_CLI_RESULT_BYTES_UNAVAILABLE')
        return result  # Exact raw output remains private, not in the journal.

    def _never_started(self,task,context):
        """A stop for a launch that never began: no durable worker reservation exists, so no Pod create was ever submitted.

        Absence AFTER a reservation is ambiguous and stays refused (ABSENCE_IS_NOT_A_STOP_RECEIPT in the controller); absence with NO reservation at all
        is definitive. The worker Pod name is READ once more, and the reservation is re-checked afterwards so a launch racing the stop is refused."""
        name=worker_pod_name(task.id)
        present=self.controller.api.read_pod(name) is not None   # STRICT (Option B): an unreadable pod API propagates; no never-started receipt without the observation
        if present:raise ValueError('CLI_NEVER_STARTED_BUT_WORKER_POD_PRESENT')
        if getattr(task,'a2a_cli_worker',None):raise ValueError('CLI_NEVER_STARTED_RACED_WITH_LAUNCH')
        return {**context,'stopped':True,'processExitVerified':True,'descendantAbsenceVerified':True,'neverStarted':True}

    def stop_and_verify(self,context):
        task=self._task(context,stop=True)
        if not getattr(task,'a2a_cli_worker',None):return self._never_started(task,context)
        self.controller.send_cancel_once(task,operation_id=context['operationId'])
        proof=self._observe(lambda:self.controller.observe_cancel(task,operation_id=context['operationId']))
        self.controller.retain_terminal(task)
        return {**context,'scopeUid':proof['scopeUid'],'stopped':proof['stopped'],
            'processExitVerified':proof['processExitVerified'],
            'descendantAbsenceVerified':proof['descendantAbsenceVerified']}

    def observe_terminal(self,context):
        task=self._task(context)
        proof=self.controller.observe_terminal(task)
        cancel=getattr(task,'a2a_cli_cancel',None)
        if isinstance(cancel,dict):
            if proof.get('cancelled') is not True or proof.get('operationId')!=cancel.get('operationId'):
                raise ValueError('CLI_RECOVERY_STOP_OPERATION_CHANGED')
        with task.persistence_lock:
            pending=task.a2a_cli_worker.get('terminalReceiptSha256') is None
        if pending:self.controller.retain_terminal(task)
        proof=self.controller.recover_terminal(task)
        if isinstance(cancel,dict) and proof.get('operationId')!=cancel.get('operationId'):
            raise ValueError('CLI_RECOVERY_STOP_OPERATION_CHANGED')
        return {**context,'scopeUid':proof['scopeUid'],'stopped':proof['stopped'],
            'processExitVerified':proof['processExitVerified'],
            'descendantAbsenceVerified':proof['descendantAbsenceVerified'],
            'outputAvailable':False}  # Metadata cannot reconstruct the answer.
