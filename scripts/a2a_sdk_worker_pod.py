"""Exact SDK variant of the same disposable private worker profile.

Construction supplies no package, execution, model or deployment admission.
The immutable image must already contain the matched admitted SDK/runtime pair.
"""
import re
from scripts.a2a_private_worker_pod import worker_pod

PACKAGE='dsh.example.com/sdk-package-admission-sha256'


def sdk_worker_pod(*,package_admission_sha256,**kwargs):
    if (not isinstance(package_admission_sha256,str)
            or not re.fullmatch(r'[a-f0-9]{64}',package_admission_sha256)
            or package_admission_sha256=='0'*64):
        raise ValueError('EXACT_SDK_PACKAGE_ADMISSION_HASH_REQUIRED')
    pod=worker_pod(**kwargs)
    pod['metadata'].setdefault('annotations',{})[PACKAGE]=package_admission_sha256
    pod['spec']['containers'][0]['command']=[
        '/usr/local/bin/python3','-I','-S','/opt/dsh/scripts/a2a_sdk_worker.py']
    return pod
