#!/usr/bin/env python3
"""Seed Claude Code's global config (CLAUDE_CONFIG_DIR/.claude.json) with platform defaults the user has not chosen yet.

Only keys that are ABSENT are added, so a choice the user makes with /config always wins. Today: copyOnSelect=false (selecting text must not overwrite
the clipboard). The file is rewritten atomically with mode 0600 and only when it changes. Never raises: start-up must not fail because of this.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

DEFAULTS = {"copyOnSelect": False}


def seed(path):
    path = Path(path)
    try:
        if not path.parent.is_dir() or not os.access(path.parent, os.W_OK):
            return "skipped: config directory missing or not writable"
        data = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return "skipped: existing file is not readable JSON (left untouched)"
            if not isinstance(data, dict):
                return "skipped: existing file is not a JSON object (left untouched)"
        added = [key for key in DEFAULTS if key not in data]
        if not added:
            return "unchanged"
        for key in added:
            data[key] = DEFAULTS[key]
        handle, temporary = tempfile.mkstemp(prefix=".claude.json.", dir=str(path.parent))
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(data, stream, indent=2)
                stream.write("\n")
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return "seeded: " + ",".join(added)
    except Exception as error:  # never block start-up
        return "skipped: " + type(error).__name__


def main(argv):
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or "/state/claude"
    target = argv[1] if len(argv) > 1 else str(Path(config_dir) / ".claude.json")
    print("seed_claude_defaults:", seed(target))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
