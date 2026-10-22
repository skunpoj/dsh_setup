"""Read-only compatibility gate for the reviewed DeepInfer candidate.

Does not import CUDA/PyTorch, build/install packages, load weights, or deploy.
Architecture eligibility is only one prerequisite, never serving acceptance.
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess

PIN = '9bd9cf243fc53ef9afbf8f04d391d989117d6ab9'
DEPENDENCIES = {
    'FlashMLA': '2e5429fc5653bab6e081f09477126f731882a6a9',
    'DeepGEMM': '1fc9c66975ee322d628b3288534ca0e9ce12a64d',
}
SOURCES = {
    'FlashMLA': ['csrc/api/common.h', 'csrc/api/sparse_decode.cpp',
                 'csrc/api/fused_norm_rope_attn_rope_cast_fwd.cpp'],
    'DeepGEMM': ['csrc/apis/mega_moe.hpp'],
}


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args],
                                   stderr=subprocess.PIPE, timeout=30)


def inspect_source(root):
    root = Path(root)
    if git(root, 'rev-parse', 'HEAD').decode().strip() != PIN:
        raise ValueError('Unreviewed DeepInfer revision; review before updating the gate')
    hashes = {}
    for name, pin in DEPENDENCIES.items():
        location = root / 'vendor' / name
        tree = git(root, 'ls-tree', 'HEAD', 'vendor/' + name).decode().split()
        if len(tree) < 3 or tree[2] != pin:
            raise ValueError('Unreviewed dependency pin: ' + name)
        if git(location, 'rev-parse', 'HEAD').decode().strip() != pin:
            raise ValueError('Dependency checkout does not match: ' + name)
        for source in SOURCES[name]:
            data = git(location, 'show', 'HEAD:' + source)
            actual = (location / source).read_text(encoding='utf-8')
            if actual != data.decode().replace('\r\n', '\n'):
                raise ValueError('Modified kernel source: ' + name + '/' + source)
            hashes[name + '/' + source] = hashlib.sha256(data).hexdigest()
    readme = git(root, 'show', 'HEAD:README.md').decode()
    if 'NVIDIA SM100 GPUs' not in readme:
        raise ValueError('Hardware declaration changed; re-review required')
    return hashes


def parse_hardware(text):
    rows = []
    for row in csv.reader(io.StringIO(text)):
        if not row:
            continue
        if len(row) != 3:
            raise ValueError('Expected name, compute_cap, driver_version from nvidia-smi')
        name, capability, driver = (v.strip() for v in row)
        parts = capability.split('.')
        if len(parts) != 2 or not all(p.isdigit() for p in parts) or not name or not driver:
            raise ValueError('Invalid GPU discovery result')
        rows.append({'name': name, 'computeCapability': [int(p) for p in parts],
                     'driverVersion': driver})
    if not rows:
        raise ValueError('No GPUs observed; refusing an empty architecture check')
    return rows


def assess(rows, hashes):
    eligible = all(r['computeCapability'][0] == 10 for r in rows)
    return {
        'schemaVersion': 1, 'engine': 'DeepInfer', 'commit': PIN,
        'dependencies': DEPENDENCIES, 'kernelBlobSHA256': hashes,
        'hardware': rows, 'offlineArchitectureEligible': eligible,
        'status': 'architecture-only-pass-runtime-unqualified' if eligible else 'blocked-unsupported-gpu',
        'productionEligible': False,
        'reason': 'Runtime, memory, correctness and DSH serving tests still required' if eligible else
                  'Pinned FlashMLA and Mega-MoE require SM100; no validated SM90 fallback exists in this candidate',
        'gpuAllocationRequested': False, 'packagesInstalled': False,
        'weightsLoaded': False, 'serviceChanged': False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--hardware-csv', type=Path,
                        help='Saved actual NVML/nvidia-smi discovery; otherwise discover locally')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    hashes = inspect_source(args.source)
    hardware = args.hardware_csv.read_text(encoding='utf-8-sig') if args.hardware_csv else subprocess.check_output(
        ['nvidia-smi', '--query-gpu=name,compute_cap,driver_version', '--format=csv,noheader'],
        text=True, timeout=20)
    result = assess(parse_hardware(hardware), hashes)
    # Preserve earlier receipts instead of replacing them.
    with args.output.open('x', encoding='utf-8') as receipt:
        json.dump(result, receipt, indent=2)
        receipt.write('\n')
    print(json.dumps({'status': result['status'], 'productionEligible': False,
                      'gpuCount': len(result['hardware'])}))
    return 0 if result['offlineArchitectureEligible'] else 78


if __name__ == '__main__':
    raise SystemExit(main())
