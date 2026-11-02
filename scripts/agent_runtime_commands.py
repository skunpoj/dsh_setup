"""One fixed, guarded command policy for broker and native workers."""


def command_for(runtime, prompt, writes, project, task_id, resume=False):
    if runtime not in {"sdk","claude","deepagents","kilo"}:
        raise ValueError("INVALID_RUNTIME")
    control=["/usr/local/bin/dsh-unattended",runtime,"--task-id",task_id,
             "--max-model-starts","1","--cwd",str(project)]
    if runtime=="sdk":
        if resume:return [*control,"--resume","--","--resume"]
        return [*control,"--","--prompt",prompt]
    if resume:raise ValueError("UNSUPPORTED_RUNTIME_RESUME")
    if runtime=="deepagents":return [*control,"--","-n",prompt]
    if runtime=="kilo":return [*control,"--","--pure","run",prompt]
    return [*control,"--","-p",prompt,"--output-format","stream-json","--verbose",
            "--permission-mode","acceptEdits" if writes else "plan"]
