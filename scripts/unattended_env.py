"""Explicit environment allowlist for unattended task processes.

The broker used to hand its WHOLE environment to the task process and dsh-unattended copied the whole parent environment into
the model client, so provider keys such as DEEPSEEK_API_KEY, Kerberos cache pointers and node preloads reached an unattended
agent outside the per-task guard. Only the names below pass; names that look like credentials are dropped even if a future
edit adds them to ALLOWED. Interactive sessions do not use this module.

DSH_CONTEXT_TOKENS, NODE_OPTIONS and DSH_MANAGED_TRANSPORT are deliberately all absent: start-dsh.sh reads DSH_CONTEXT_TOKENS once at
startup to decide whether to load the managed inference transport (a timeout/budget shim scoped to the real gateway origin, not
to the loopback guard), so passing the flag without its preload would half-set a mode; no task client reads it.
"""
import re

ALLOWED = frozenset({
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "COLORTERM", "TZ", "TMPDIR", "USER", "LOGNAME", "SHELL",
    "DSH_ENVIRONMENT", "DSH_HOME", "PYTHONPATH",
    "DSH_UNATTENDED_TASK", "DSH_CORRELATION_ID", "DSH_GUARDED_MODEL_BASE_URL",
})
CREDENTIAL_NAME = re.compile(r"(^|_)(API_?KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIALS?|PRIVATE_?KEY)(_|$)", re.IGNORECASE)


def minimal_environment(parent):
    return {name: value for name, value in parent.items()
            if name in ALLOWED and not CREDENTIAL_NAME.search(name) and isinstance(value, str)}
