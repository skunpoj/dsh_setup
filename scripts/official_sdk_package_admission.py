"""Read-only exact SDK wheel/content admission; never imports SDK code."""
import base64
import csv
import hashlib
import importlib.abc
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import zipfile

VERSION = "0.2.2a2"
SOURCE = "ce7073d51254c26cd63b22a60835b8f948deb447"
ADMISSION = Path("/etc/dsh-native-admission/official-sdk-package.json")
INSTALLED = Path("/opt/dsh/deepagents/lib/python3.14/site-packages")
WHEEL = Path("/packages/approved/python/deepseek_harness_sdk-0.2.2a2-py3-none-any.whl")


def unique_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value: raise ValueError("DUPLICATE_SDK_ADMISSION_FIELD")
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=pairs)


def protected_bytes(path, limit):
    path = Path(path)
    for component in (path, *path.parents):
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("UNPROTECTED_SDK_ADMISSION_CONTENT")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode): raise ValueError("SDK_REGULAR_FILE_REQUIRED")
        with os.fdopen(fd, "rb", closefd=False) as stream: raw = stream.read(limit + 1)
        if len(raw) > limit: raise ValueError("SDK_ADMISSION_CONTENT_TOO_LARGE")
        return raw
    finally: os.close(fd)


def verify_sdk_admission(*, admission_path=ADMISSION, installed=INSTALLED, wheel=WHEEL,
                         reader=protected_bytes):
    raw = reader(admission_path, 16384)
    manifest = unique_json(raw)
    required = {"kind", "sourceCommit", "sdkVersion", "runtimeVersion", "sdkWheelSha256", "installedRecordSha256"}
    if (not isinstance(manifest, dict) or set(manifest) != required
            or manifest["kind"] != "DSH_OFFICIAL_SDK_PACKAGE_V1"
            or manifest["sourceCommit"] != SOURCE
            or manifest["sdkVersion"] != VERSION or manifest["runtimeVersion"] != VERSION
            or any(not isinstance(manifest[k], str) or not re.fullmatch(r"[a-f0-9]{64}", manifest[k])
                   or manifest[k] == "0" * 64 for k in ("sdkWheelSha256", "installedRecordSha256"))):
        raise ValueError("INVALID_SDK_PACKAGE_ADMISSION")
    wheel_raw = reader(wheel, 8 * 1024 * 1024)
    if hashlib.sha256(wheel_raw).hexdigest() != manifest["sdkWheelSha256"]:
        raise ValueError("SDK_WHEEL_ADMISSION_HASH_MISMATCH")
    dist = f"deepseek_harness_sdk-{VERSION}.dist-info"
    record_raw = reader(installed / dist / "RECORD", 1024 * 1024)
    if hashlib.sha256(record_raw).hexdigest() != manifest["installedRecordSha256"]:
        raise ValueError("SDK_INSTALLED_RECORD_HASH_MISMATCH")
    records = {}
    for row in csv.reader(io.StringIO(record_raw.decode("utf-8"))):
        if len(row) != 3 or row[0] in records: raise ValueError("INVALID_SDK_INSTALLED_RECORD")
        records[row[0]] = row[1:]
    payloads = {}
    with zipfile.ZipFile(io.BytesIO(wheel_raw)) as archive:
        entries = archive.infolist()
        if len({i.filename for i in entries}) != len(entries) or sum(i.file_size for i in entries) > 16 * 1024 * 1024:
            raise ValueError("INVALID_SDK_WHEEL_ENTRIES")
        for info in entries:
            name = info.filename; path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("SDK_WHEEL_PATH_REFUSED")
            if info.is_dir(): continue
            if not (name.startswith("deepseek_harness/") or name in (dist + "/METADATA", dist + "/WHEEL")):
                continue
            content = archive.read(info)
            digest = hashlib.sha256(content).digest()
            expected = ["sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode(), str(len(content))]
            if records.get(name) != expected or reader(installed / name, 4 * 1024 * 1024) != content:
                raise ValueError("SDK_INSTALLED_CONTENT_MISMATCH")
            payloads[name] = digest.hex()
    if "deepseek_harness/__init__.py" not in payloads:
        raise ValueError("SDK_PACKAGE_ENTRY_REQUIRED")
    for file in (installed / "deepseek_harness").rglob("*"):
        if file.is_symlink(): raise ValueError("SDK_PACKAGE_SYMLINK_REFUSED")
        if file.is_file() and file.suffix != ".pyc" and file.relative_to(installed).as_posix() not in payloads:
            raise ValueError("UNADMITTED_SDK_PACKAGE_FILE")
    return {"admissionSha256": hashlib.sha256(raw).hexdigest(), "sdkVersion": VERSION,
        "runtimeVersion": VERSION, "sourceCommit": SOURCE, "sdkWheelSha256": manifest["sdkWheelSha256"],
        "installedRoot": str(installed), "payloads": payloads}


def install_verified_sdk_imports(admission, *, reader=protected_bytes):
    """Child-only finder: compile admitted source; never consume cached .pyc."""
    if any(k == "deepseek_harness" or k.startswith("deepseek_harness.") for k in sys.modules):
        raise ValueError("SDK_IMPORTED_BEFORE_CONTENT_ADMISSION")
    root = Path(admission["installedRoot"]); payloads = admission["payloads"]
    class Loader(importlib.abc.Loader):
        def __init__(self, path): self.path = path
        def create_module(self, spec): return None
        def exec_module(self, module):
            raw = reader(root / self.path, 4 * 1024 * 1024)
            if hashlib.sha256(raw).hexdigest() != payloads[self.path]:
                raise ValueError("SDK_SOURCE_CHANGED_BEFORE_IMPORT")
            module.__file__ = str(root / self.path)
            module.__cached__ = None
            exec(compile(raw, str(root / self.path), "exec"), module.__dict__)
    class Finder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname != "deepseek_harness" and not fullname.startswith("deepseek_harness."):
                return None
            module = fullname.replace(".", "/")
            for name, package in ((module + "/__init__.py", True), (module + ".py", False)):
                if name in payloads:
                    spec = importlib.util.spec_from_loader(fullname, Loader(name), is_package=package)
                    spec.origin = str(root / name)
                    if package: spec.submodule_search_locations = [str(root / module)]
                    return spec
            raise ImportError("SDK_MODULE_NOT_ADMITTED")
    finder = Finder(); sys.meta_path.insert(0, finder)
    return finder
