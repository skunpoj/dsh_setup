"""One fixed, guarded command policy for broker and native workers."""

# A headless Claude Code task has no approver, so under acceptEdits every Bash command needs approval and a banking task cannot unzip its data or run the numeric
# Python (measured: run 1 of 10 Nov, 19 requests, no deliverable). Admitted banking tasks (a server-admitted cap above 1, see scripts/banking_allowance.py) get exactly
# TWO Bash permissions and nothing else (the user's hard rule): the exact commands `dsh-banking-python script.py` and `dsh-banking-unzip bank.zip`. A Claude Code Bash
# rule WITHOUT a trailing :* matches that exact command string only, so other file names, extra arguments, pipes, redirection, variables, -c and every other command
# (ls, cat, head, wc, sha256sum, mkdir, cd, cp, raw python/unzip) need an approval nobody can give and are refused. The agent writes script.py with Claude Code's own
# Write tool (permitted by acceptEdits inside the project directory). The root-owned wrappers (integrations/managed-agents/container/dsh-banking-tools.py) ALSO accept only
# these exact argument forms, so the same two commands are the only ones that work on the Deep Agents route, whose -S list matches the first token only.
BANKING_CLAUDE_ALLOWED_TOOLS = ("Bash(dsh-banking-python script.py)", "Bash(dsh-banking-unzip bank.zip)")


def command_for(runtime, prompt, writes, project, task_id, resume=False, max_model_starts=1, banking_tools=False, banking_accounting_only=False):
    if runtime not in {"sdk","claude","deepagents","kilo"}:
        raise ValueError("INVALID_RUNTIME")
    # The cap is the guard's per-task bound on distinct UPSTREAM REQUESTS. Ordinary tasks and the native workers use the default 1; only the broker passes a larger
    # value, and only from scripts/banking_allowance.py (a root-owned server file plus a persistent ledger).
    if max_model_starts is None and not (banking_accounting_only is True and runtime in {"claude","deepagents"} and not resume):raise ValueError("EXPLICIT_STANDING_BANKING_COMMAND_REQUIRED")
    if max_model_starts is not None and (type(max_model_starts) is not int or not 1<=max_model_starts<=32):
        raise ValueError("INVALID_MODEL_START_CAP")
    if banking_tools and not (runtime=="claude" and writes is True and not resume and (max_model_starts is None or max_model_starts>1)):
        raise ValueError("BANKING_TOOLS_NOT_ADMITTED")     # only an admitted (cap above 1), writable, non-resumed Claude banking task
    control=["/usr/local/bin/dsh-unattended",runtime,"--task-id",task_id,
             "--max-model-starts","standing-banking" if max_model_starts is None else str(max_model_starts),"--cwd",str(project)]
    if banking_tools and runtime=="claude":control.append("--banking-gate")   # turns the managed PreToolUse deny-by-default hook on for THIS task only
    if runtime=="sdk":
        if resume:return [*control,"--resume","--","--resume"]
        return [*control,"--","--prompt",prompt]
    if resume:raise ValueError("UNSUPPORTED_RUNTIME_RESUME")
    if runtime=="deepagents":return [*control,"--","-n",prompt]
    if runtime=="kilo":return [*control,"--","--pure","run",prompt]
    command=[*control,"--","-p",prompt,"--output-format","stream-json","--verbose",
             "--permission-mode","acceptEdits" if writes else "plan"]
    if banking_tools:command+=["--allowedTools",",".join(BANKING_CLAUDE_ALLOWED_TOOLS)]
    return command
