"""Fail closed on GPU failure diagnostics before advancing a trial stage.

Read a complete, stage-scoped model log from stdin or a UTF-8 file. This is a
log acceptance gate, not a live health check or authorization to run a trial.
Only counts are emitted; prompts, addresses and raw log lines are never echoed.
"""
import argparse
import json
import re
import sys
from pathlib import Path

PATTERNS = {
    "allocatorMappingWarnings": r"memory mapping failed with OOM",
    "cudaOutOfMemory": r"(?:CUDA\s+(?:error:\s*)?out of memory|torch\.OutOfMemoryError)",
    "schedulerAssertions": r"AssertionError",
    "illegalMemoryAccess": r"(?:illegal memory access|device-side assert triggered)",
    "tracebacks": r"Traceback \(most recent call last\)",
}


def inspect_log(text):
    counts = {key: len(re.findall(pattern, text, re.I)) for key, pattern in PATTERNS.items()}
    progress = len(re.findall(r"(?:Prefill batch|Decode batch)", text))
    valid = bool(text.strip()) and progress > 0
    return {"passed": valid and not any(counts.values()),
            "inferenceProgressRecords": progress, "diagnosticCounts": counts,
            "scope": "Provided full-stage model log only; runtime identity and request results require separate verification"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", nargs="?", default="-", help="UTF-8 log file, or - for stdin")
    args = parser.parse_args(argv)
    try:
        text = sys.stdin.read() if args.log == "-" else Path(args.log).read_text(encoding="utf-8", errors="replace")
    except OSError:
        print(json.dumps({"passed": False, "error": "Log unavailable"}))
        return 2
    result = inspect_log(text)
    print(json.dumps(result))
    if not result["inferenceProgressRecords"]:
        return 2
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
