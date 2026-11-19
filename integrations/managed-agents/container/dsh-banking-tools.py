#!/usr/bin/env python3
"""Bounded tools for the banking exercise in a managed Deep Agents task (installed as dsh-banking-python and dsh-banking-unzip).

The Deep Agents worker has only file tools (ls/read_file/write_file/grep); read_file is UTF-8 text, so a ZIP is unreadable and the numeric Python cannot run.
These two commands are the ONLY shell commands the launcher allow-lists, and only for a task admitted by the root-owned banking allowance:
  dsh-banking-unzip bank.zip        extract bank.zip (in the task directory) into the new directory bank_unzipped (no traversal, no symlinks, size caps)
  dsh-banking-python script.py      run script.py (in the task directory) with the numeric interpreter /opt/dsh/numeric/bin/python (no -c, no -m, no stdin program)
The command line accepts EXACTLY these two forms (the user's hard rule): no other file name, no extra argument, no destination. The library functions below stay general.
Both refuse paths outside the task directory (the current directory, which must be under /workspace). There is no network tool and the pods have no egress.
"""
import os
import sys
import zipfile
from pathlib import Path

NUMERIC_PYTHON = "/opt/dsh/numeric/bin/python"
EXACT_SCRIPT = "script.py"
EXACT_ZIP = "bank.zip"
BASE = Path("/workspace")
MAX_MEMBERS = 2000
MAX_MEMBER_BYTES = 256 << 20
MAX_TOTAL_BYTES = 512 << 20
CPU_SECONDS = 1800
FILE_BYTES = 1 << 30


def task_root(base=None):
    base = Path(base or BASE).resolve()
    root = Path.cwd().resolve()
    if root == base or not root.is_relative_to(base):
        raise ValueError("Run from the task project directory under /workspace")
    return root


def inside(root, name, *, must_exist=True):
    if not name or "\0" in name or name.startswith("-"):
        raise ValueError("Invalid path")
    path = (root / name).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError("Path is outside the task directory: " + name)
    if must_exist and not path.exists():
        raise ValueError("Not found: " + name)
    return path


def member_target(destination, name):
    if not name or name.startswith(("/", "\\")) or "\\" in name or ":" in name.split("/", 1)[0] or "\0" in name:
        raise ValueError("Unsafe ZIP member name")
    target = (destination / name).resolve()
    if not target.is_relative_to(destination):
        raise ValueError("ZIP member escapes the destination")
    return target


def unzip(root, archive_name, destination_name=None):
    archive = inside(root, archive_name)
    if not archive.is_file() or archive.suffix.lower() != ".zip":
        raise ValueError("Expected a .zip file inside the task directory")
    destination = inside(root, destination_name or (archive.stem + "_unzipped"), must_exist=False)
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError("Destination must be new or empty")
    written = []
    total = 0
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if len(members) > MAX_MEMBERS:
            raise ValueError("Too many ZIP members")
        if sum(m.file_size for m in members) > MAX_TOTAL_BYTES or any(m.file_size > MAX_MEMBER_BYTES for m in members):
            raise ValueError("ZIP is too large")
        destination.mkdir(parents=True, exist_ok=True)
        for member in members:
            target = member_target(destination, member.filename)
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("ZIP symlinks are refused")
            if member.flag_bits & 0x1:
                raise ValueError("Encrypted ZIP members are refused")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            size = 0
            with bundle.open(member) as source, open(target, "xb") as sink:
                while True:
                    chunk = source.read(1 << 20)
                    if not chunk:
                        break
                    size += len(chunk)
                    total += len(chunk)
                    if size > MAX_MEMBER_BYTES or total > MAX_TOTAL_BYTES:
                        raise ValueError("ZIP expands beyond the size cap")
                    sink.write(chunk)
            written.append((target.relative_to(root).as_posix(), size))
    return written


def python_command(root, script_name, arguments):
    script = inside(root, script_name)
    if not script.is_file() or script.suffix != ".py":
        raise ValueError("Expected a .py script inside the task directory")
    if any("\0" in a for a in arguments):
        raise ValueError("Invalid argument")
    return [NUMERIC_PYTHON, "-E", "-s", str(script), *arguments]


def python_environment():
    return {"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", "/home/dsh"), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
            "OMP_NUM_THREADS": "4", "OPENBLAS_NUM_THREADS": "4", "MPLBACKEND": "Agg"}


def main(argv=None, name=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    name = name or Path(sys.argv[0]).name
    try:
        root = task_root()
        if name == "dsh-banking-unzip":
            if argv != [EXACT_ZIP]:
                raise ValueError("Usage: dsh-banking-unzip bank.zip (no other form is allowed)")
            for path, size in unzip(root, EXACT_ZIP):
                print(f"{size}\t{path}")
            return 0
        if name == "dsh-banking-python":
            if argv != [EXACT_SCRIPT]:
                raise ValueError("Usage: dsh-banking-python script.py (no other form is allowed)")
            command = python_command(root, EXACT_SCRIPT, [])
            import resource  # POSIX only; the image is Linux
            resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
            resource.setrlimit(resource.RLIMIT_FSIZE, (FILE_BYTES, FILE_BYTES))
            os.execve(command[0], command, python_environment())
        raise ValueError("Unknown tool")
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        print("Refused: " + str(error), file=sys.stderr)
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
