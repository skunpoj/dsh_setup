"""Actual installed-wheel native approval fixture; invoked only network-isolated.

This is a producer qualification, not web-broker/OpenShell acceptance. The
pinned upstream fixture rejects before model inference. No real key is used.
"""
from concurrent.futures import ThreadPoolExecutor
import importlib.metadata
import json
from pathlib import Path
import sys


def main():
    if sys.platform != 'linux': raise ValueError('LINUX_PRODUCER_REQUIRED')
    for name in ('deepseek-harness-sdk', 'deepseek-harness-runtime-bin'):
        if importlib.metadata.version(name) != '0.2.2a2':
            raise ValueError('INSTALLED_WHEEL_PAIR_MISMATCH')
    import deepseek_harness
    from deepseek_harness import HarnessClient, HarnessConfig
    from deepseek_harness_runtime import bundled_runtime_path
    from pydantic import BaseModel
    class EmptyResponse(BaseModel):
        pass
    if not Path(deepseek_harness.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
        raise ValueError('INSTALLED_SDK_ORIGIN_REQUIRED')
    binary = Path(bundled_runtime_path()).resolve()
    if not binary.is_relative_to(Path(sys.prefix).resolve()):
        raise ValueError('INSTALLED_RUNTIME_ORIGIN_REQUIRED')
    fixture = Path('/work/source/packages/sdk/server/tests/fixtures/approval.mjs')
    output = Path('/work/out/native-approval'); output.mkdir()
    observations = []
    for outcome in ('allowed-once', 'rejected'):
        root = output / outcome; root.mkdir()
        marker = root / 'approved.txt'; patch = root / 'fixture.yml'
        patch.write_text('- insert:\n    - id: approval-fixture\n      name: ' + json.dumps(str(fixture))
                         + '\n      config:\n        stopAfterApproval: true\n        path: ' + json.dumps(str(marker)) + '\n')
        with ThreadPoolExecutor(max_workers=1) as reader:
            with HarnessClient(HarnessConfig(dsh_bin=str(binary), cwd=str(root), patches=(str(patch),),
                    request_timeout_seconds=20, shutdown_timeout_seconds=20,
                    env={'HOME':str(root),'DSH_HOME':str(root/'home'),
                         'DSH_PERMISSION_MODE':'workspace-write','DSH_TELEMETRY_DISABLED':'1',
                         'DEEPSEEK_API_KEY':'keyless-no-model-call'})) as client:
                client.initialize(cwd=str(root), provider='deepseek-official',
                                  model='deepseek-v4-flash', approval_requests=True)
                process = client._proc  # Pinned ce7073 client; retain actual process observation across close.
                if process is None: raise ValueError('NATIVE_PROCESS_REQUIRED')
                client.session_prompt('main',[{'type':'text','text':'Request the marker write.'}])
                request = reader.submit(client.next_request).result(timeout=20)
                if (request.method != 'approval/request' or request.payload.get('toolName') != 'fixture-write'
                        or request.payload.get('sessionId') != 'main'):
                    raise ValueError('EXACT_NATIVE_APPROVAL_REQUIRED')
                client.respond(request.id, {'outcome':outcome})
                client.request('session/wait', {'sessionId':'main'}, response_model=EmptyResponse)
            expected = outcome == 'allowed-once'
            if marker.exists() != expected or (expected and marker.read_bytes() != b'approved\n'):
                raise ValueError('NATIVE_APPROVAL_RESULT_MISMATCH')
            if process.poll() is None: raise ValueError('NATIVE_PROCESS_STILL_RUNNING')
            observations.append({'outcome':outcome,'markerExists':marker.exists(),
                                 'markerContentChecked':expected,'nativeProcessExited':True,
                                 'nativeExitCode':process.returncode,'descendantExitQualified':False})
    (output/'results.json').write_text(json.dumps({'scope':'Installed-wheel producer fixture only',
        'modelCallsIntended':0,'observations':observations},indent=2)+'\n')


if __name__ == '__main__': main()
