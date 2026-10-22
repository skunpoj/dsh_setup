"""Collect the gateway and its literal local CommonJS dependencies for deployment."""
import hashlib
import json
import re
from pathlib import Path

_LOCAL_REQUIRE = re.compile(r"require\(\s*['\"](\./[^'\"]+)['\"]\s*\)")

def gateway_sources(root):
    directory = Path(root) / "scripts"
    pending = ["auth_proxy.js"]
    result = {}
    while pending:
        name = pending.pop()
        if name in result:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.js", name):
            raise ValueError("Unsupported gateway dependency path: " + name)
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("Missing regular gateway source: " + name)
        source = path.read_text(encoding="utf-8")
        result[name] = source
        for relative in _LOCAL_REQUIRE.findall(source):
            member = relative[2:]
            if not member.endswith(".js"):
                member += ".js"
            if not re.fullmatch(r"[A-Za-z0-9_-]+\.js", member):
                raise ValueError("Unsupported gateway local require: " + relative)
            pending.append(member)
    # This fixed Python launcher is sent to the owner's existing terminal.
    # Explicitly package it; it is not a CommonJS dependency.
    if "jupyter_on_demand.js" in result:
        launcher = directory / "jupyter_launcher.py"
        if launcher.is_symlink() or not launcher.is_file():
            raise ValueError("Missing regular gateway source: jupyter_launcher.py")
        result[launcher.name] = launcher.read_text(encoding="utf-8")
    return dict(sorted(result.items()))

def gateway_sources_sha256(source):
    return hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
