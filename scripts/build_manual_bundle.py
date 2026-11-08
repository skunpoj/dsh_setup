"""Build one bounded DSH HTML manual package from exact committed source bytes."""
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
ALLOWED = {".html", ".png", ".svg", ".json", ".vtt", ".mp4"}
MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = []

    def handle_starttag(self, _tag, attrs):
        for key, value in attrs:
            if key in {"href", "src"} and value:
                self.values.append(value)


def committed(ref, name):
    return subprocess.check_output(
        ["git", "show", f"{ref}:docs/{name}"], cwd=ROOT
    )


def build(output: Path, ref: str):
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", "--end-of-options", ref + "^{commit}"],
        cwd=ROOT,
        text=True,
    ).strip()
    if len(commit) != 40:
        raise ValueError("A complete Git commit is required")
    names = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", commit, "docs"], cwd=ROOT, text=True
    ).splitlines()
    pending = sorted(
        name.removeprefix("docs/")
        for name in names
        if name.startswith("docs/") and PurePosixPath(name).parent == PurePosixPath("docs") and name.endswith(".html")
    )
    if {"index.html", "DSH_PLATFORM_GUIDE.html"} - set(pending):
        raise ValueError("Canonical documentation entry points are missing")
    entries, total = {}, 0
    while pending:
        name = pending.pop(0)
        if name in entries:
            continue
        pure = PurePosixPath(name)
        if pure.is_absolute() or ".." in pure.parts or pure.suffix not in ALLOWED:
            raise ValueError("Unsafe documentation member: " + name)
        data = committed(commit, name)
        if len(data) > MAX_FILE:
            raise ValueError("Documentation member exceeds limit: " + name)
        total += len(data)
        if total > MAX_TOTAL:
            raise ValueError("Documentation bundle exceeds limit")
        target = output / pure
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        entries[name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        if pure.suffix == ".html":
            parser = Links()
            parser.feed(data.decode("utf-8"))
            for value in parser.values:
                url = urlsplit(value)
                if url.scheme or url.netloc or not url.path or url.path.startswith("/"):
                    continue
                child = (pure.parent / PurePosixPath(unquote(url.path)))
                if ".." not in child.parts and child.suffix in ALLOWED:
                    tree_path = "docs/" + child.as_posix()
                    if tree_path in names and child.as_posix() not in entries:
                        pending.append(child.as_posix())
    manifest = {"schema": "dsh-manual-bundle/v1", "sourceCommit": commit, "files": dict(sorted(entries.items())), "bytes": total}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--git-ref", required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = build(args.output, args.git_ref)
    print(json.dumps({"files": len(result["files"]), "bytes": result["bytes"], "sourceCommit": result["sourceCommit"]}))
