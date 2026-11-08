"""Configured private-workspace executors; no fallback or credential discovery."""


class PrivateA2AExecutor:
    def __init__(self, *, sdk_service, cli_service):
        self.sdk_service = sdk_service
        self.cli_service = cli_service

    @property
    def subject(self):
        return self.sdk_service.subject if self.sdk_service is not None else None

    @property
    def qualified(self):
        return (self.sdk_service is not None and self.sdk_service.qualified is True
                and self.cli_service is not None and self.cli_service.qualified is True
                and self.sdk_service.subject == self.cli_service.subject)

    def __call__(self, child):
        if not self.qualified or child.request.get("backend") != "private":
            raise ValueError("A2A_PRIVATE_EXECUTORS_NOT_QUALIFIED")
        runtime = child.request["runtime"]
        if runtime == "sdk":
            return self.sdk_service.run_task(self.sdk_service.subject, child)
        if runtime in {"claude", "deepagents"}:
            return self.cli_service.run_task(self.cli_service.subject, child)
        raise ValueError("A2A_RUNTIME_REFUSED")
