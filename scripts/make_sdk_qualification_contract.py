"""Hash-pinned execution contract for one qualification run (OpenShell lane). Local only: it lists files with their sha256 and never contacts anything.

Same discipline as the W3-W10 wheel runs: a runner verifies every listed file against this contract at EVERY step, so a later fix needs a new contract, not an edit.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

KIND = "DSH_SDK_QUALIFICATION_EXECUTION_CONTRACT_V1"


def build_contract(*, owner_commit, operation_id, namespace, files, continues=None, worktree=None, source_commit=None, case_id=None, model_starts=None):
    if not re.fullmatch(r"[a-f0-9]{40}", str(owner_commit)):
        raise ValueError("OWNER_COMMIT_REQUIRED")
    if not re.fullmatch(r"[a-f0-9]{32}", str(operation_id)) or operation_id == "0" * 32:
        raise ValueError("OPERATION_ID_32_HEX_REQUIRED")
    if not re.fullmatch(r"dsh-a2a-[a-z0-9][a-z0-9-]{0,54}", str(namespace)):
        raise ValueError("A2A_OWNED_TEST_NAMESPACE_REQUIRED")
    entries = []
    seen = set()
    for item in files:
        path = Path(item)
        if not path.is_file() or path.is_symlink() or str(path) in seen:
            raise ValueError("REGULAR_UNIQUE_FILE_REQUIRED:" + str(path))
        seen.add(str(path))
        entries.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    if not entries:
        raise ValueError("FILES_REQUIRED")
    contract = {"kind": KIND, "ownerCommit": owner_commit, "operationId": operation_id, "namespace": namespace, "files": entries,
                "continuesRun": continues, "executionCount": 1, "productionAllowed": False}
    if worktree is not None or source_commit is not None:   # P3: where the runner finds the reviewed helper, and the source commit the image carries
        if not re.fullmatch(r"[a-f0-9]{40}", str(source_commit)) or not worktree or not Path(worktree).is_dir():
            raise ValueError("WORKTREE_AND_SOURCE_COMMIT_REQUIRED_TOGETHER")
        contract["worktree"] = str(worktree)
        contract["sourceCommit"] = source_commit
    if case_id is not None or model_starts is not None:   # one disposable Job per group of <= 3 model starts: the lease allowance is pinned, the case id is informational
        if not isinstance(case_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}", case_id) or type(model_starts) is not int or not 0 <= model_starts <= 3:
            raise ValueError("CASE_ID_AND_MODEL_STARTS_0_TO_3_REQUIRED_TOGETHER")
        contract["caseId"] = case_id
        contract["modelStarts"] = model_starts
    return contract


def verify_contract(contract):
    """What a runner does at every step: every file must still hash to the pinned value."""
    if contract.get("kind") != KIND or contract.get("executionCount") != 1 or contract.get("productionAllowed") is not False:
        raise ValueError("CONTRACT_IDENTITY_DRIFT")
    for entry in contract["files"]:
        if hashlib.sha256(Path(entry["path"]).read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("CONTRACT_HASH_DRIFT:" + entry["path"])
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner-commit", required=True)
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--worktree", default=None)
    parser.add_argument("--source-commit", default=None)
    parser.add_argument("--case-id", default=None)
    parser.add_argument("--model-starts", type=int, default=None)
    parser.add_argument("files", nargs="+")
    args = parser.parse_args(argv)
    try:
        contract = build_contract(owner_commit=args.owner_commit, operation_id=args.operation_id, namespace=args.namespace, files=args.files,
                                  worktree=args.worktree, source_commit=args.source_commit,
                                  case_id=args.case_id, model_starts=args.model_starts)
        with open(args.out, "x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(contract, indent=2) + "\n")
    except (ValueError, OSError) as error:
        print("CONTRACT_REFUSED:" + str(error), file=sys.stderr)
        return 2
    print(hashlib.sha256(Path(args.out).read_bytes()).hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
