#!/opt/dsh/deepagents/bin/python
"""Test-only entry for the official SDK; not a resumable production launcher."""
import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, "/opt/dsh/scripts")
from official_sdk_task import qualify


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    options = parser.parse_args()
    project = Path.cwd().resolve(strict=True)
    if not project.is_relative_to(Path("/workspace").resolve()):
        raise ValueError("PRIVATE_WORKSPACE_REQUIRED")
    # The broker already owns /state/web-tasks/<task>. Use a distinct private
    # root so its existing task journal cannot collide with our start fence.
    state_root = Path("/state/official-sdk-qualification")
    state_root.mkdir(mode=0o700, exist_ok=True)
    response = qualify(options.prompt,
                       task_id=os.environ.get("DSH_UNATTENDED_TASK", ""),
                       project=project, state_root=state_root,
                       guard_url=os.environ.get("DSH_GUARDED_MODEL_BASE_URL", ""))
    print(response, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
