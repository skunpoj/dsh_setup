#!/opt/dsh/deepagents/bin/python
"""Run one resumable DSH Python SDK task and emit JSON Lines events."""
import argparse
import json
import os
from pathlib import Path
import re
import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from dsh_deepagents_sdk import create_dsh_agent

TASK_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def serializable(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serializable(item) for item in value]
    if hasattr(value, "model_dump"):
        return serializable(value.model_dump())
    return str(value)


def contains_interrupt(value):
    if isinstance(value, dict):
        return "__interrupt__" in value or any(contains_interrupt(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_interrupt(item) for item in value)
    return False


def emit(kind, value):
    print(json.dumps({"type": kind, "data": serializable(value)}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--prompt")
    group.add_argument("--resume", action="store_true")
    options = parser.parse_args()
    task = os.environ.get("DSH_UNATTENDED_TASK", "")
    if not TASK_ID.fullmatch(task):
        raise ValueError("managed task id required")
    project = Path.cwd().resolve()
    if not project.is_relative_to(Path("/workspace").resolve()):
        raise ValueError("private workspace project required")
    state = Path("/state/web-tasks") / task
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    database = sqlite3.connect(state / "sdk-checkpoints.sqlite3", check_same_thread=False)
    agent = create_dsh_agent(project, checkpointer=SqliteSaver(database))
    config = {"configurable": {"thread_id": task}}
    request = Command(resume=True) if options.resume else {"messages": [{"role": "user", "content": options.prompt}]}
    interrupted = False
    for chunk in agent.stream(request, config=config, stream_mode=["messages", "updates"], version="v2"):
        interrupted = interrupted or contains_interrupt(chunk)
        emit("sdk_event", chunk)
    database.close()
    if interrupted:
        emit("approval_required", {"taskId": task})
        return 75
    emit("completed", {"taskId": task})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
