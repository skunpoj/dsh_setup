"""Generate the SDK package admission descriptor (kind DSH_OFFICIAL_SDK_PACKAGE_V1) for the native qualification composition.

official_sdk_package_admission.verify_sdk_admission() reads /etc/dsh-native-admission/official-sdk-package.json and checks it against the approved wheel and the
INSTALLED dist-info RECORD. Nothing in the repository wrote that file. This generator does, and refuses unless:
  * the wheel's sha256 equals the independently admitted value passed on the command line (the sealed producer receipt, ledger WHEEL-W10-SEALED),
  * the installed RECORD exists and the installed files match the wheel (the real verifier is run on the result before anything is written).
No network, no cluster, no credential. The descriptor is written exclusively (never over an existing file) and read-only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import official_sdk_package_admission as package  # noqa: E402

SHA256 = re.compile(r"[a-f0-9]{64}")
KIND = "DSH_OFFICIAL_SDK_PACKAGE_V1"


class PackageAdmissionRefused(ValueError):
    pass


def plain_reader(path, limit):
    """Bounded regular-file read for the generator's self-check; ownership is a property of the deployed file, not of this build-time read."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise PackageAdmissionRefused("REGULAR_FILE_REQUIRED:" + path.name)
    raw = path.read_bytes()
    if len(raw) > limit:
        raise PackageAdmissionRefused("FILE_TOO_LARGE:" + path.name)
    return raw


def build_descriptor(*, wheel_raw, installed_record_raw, trusted_sdk_wheel_sha256):
    if not isinstance(trusted_sdk_wheel_sha256, str) or SHA256.fullmatch(trusted_sdk_wheel_sha256) is None or trusted_sdk_wheel_sha256 == "0" * 64:
        raise PackageAdmissionRefused("UNBOUND_TRUSTED_SDK_WHEEL_SHA256")
    if hashlib.sha256(wheel_raw).hexdigest() != trusted_sdk_wheel_sha256:
        raise PackageAdmissionRefused("SDK_WHEEL_NOT_THE_ADMITTED_ONE")
    return {"kind": KIND, "sourceCommit": package.SOURCE, "sdkVersion": package.VERSION, "runtimeVersion": package.VERSION,
            "sdkWheelSha256": trusted_sdk_wheel_sha256, "installedRecordSha256": hashlib.sha256(installed_record_raw).hexdigest()}


def generate(*, wheel, installed, trusted_sdk_wheel_sha256, out):
    wheel, installed, out = Path(wheel), Path(installed), Path(out)
    if out.exists() or out.is_symlink():
        raise PackageAdmissionRefused("OUTPUT_MUST_BE_NEW")
    record = installed / ("deepseek_harness_sdk-%s.dist-info" % package.VERSION) / "RECORD"
    descriptor = build_descriptor(wheel_raw=plain_reader(wheel, 8 * 1024 * 1024), installed_record_raw=plain_reader(record, 1024 * 1024),
                                  trusted_sdk_wheel_sha256=trusted_sdk_wheel_sha256)
    raw = (json.dumps(descriptor, sort_keys=True, indent=2) + "\n").encode("utf-8")
    # round trip: the real verifier, with the same wheel and installed tree, must accept exactly these bytes
    scratch = out.with_name(out.name + ".check")
    if scratch.exists():
        raise PackageAdmissionRefused("SCRATCH_MUST_BE_NEW")
    try:
        scratch.write_bytes(raw)
        try:
            package.verify_sdk_admission(admission_path=scratch, installed=installed, wheel=wheel, reader=plain_reader)
        except Exception as error:  # the verifier raises plain ValueError codes
            raise PackageAdmissionRefused("ROUND_TRIP_REFUSED:" + str(error)) from error
    finally:
        scratch.unlink(missing_ok=True)
    with open(out, "xb") as handle:
        handle.write(raw)
    os.chmod(out, 0o444)
    return descriptor


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("wheel", "installed", "trusted-sdk-wheel-sha256", "out"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args(argv)
    try:
        descriptor = generate(wheel=args.wheel, installed=args.installed, trusted_sdk_wheel_sha256=args.trusted_sdk_wheel_sha256, out=args.out)
    except (PackageAdmissionRefused, ValueError, OSError) as error:
        print("PACKAGE_ADMISSION_REFUSED:" + str(error), file=sys.stderr)
        return 2
    print(json.dumps(descriptor, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
