#!/usr/bin/env python3
"""Protected control-plane entry point of the native-qualification broker (TEST namespace, disposable Job, uid 0).

Thin shell around scripts/native_qualification_compose.run_entry: it supplies the real files and classes; the sequence,
the refusal codes and the exit codes live in the tested library. It never writes the server admission, never prints file
contents or key material, and holds the deployment observer only inside the SDK service it configures.

Exit codes: 0 served and stopped, 1 refused (fixed code on stderr), 3 ADMISSION_NOT_DELIVERED,
4 PROTECTED_PROVIDER_RUNTIME_NOT_COMPOSED (the provider-capture/lease/workspace pieces of the composition are not
installed yet; fail closed).
"""
import importlib.util
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path[:0] = ["/opt/dsh"]
from scripts import native_qualification_compose as compose
from scripts.official_sdk_bootstrap import configure as configure_official_sdk
from scripts.official_sdk_deployment_observer import OfficialSDKDeploymentObserver
from scripts.official_sdk_executing_identity import ROOT as IDENTITY_ROOT, ExecutingPodIdentity, read_fixed
from scripts.official_sdk_package_admission import protected_bytes, unique_json
from scripts.official_sdk_test_api import FixedQualificationReadAPI, ProtectedQualificationRequester

ADMISSION = "/etc/dsh-native-admission/official-sdk-server.json"
BROKER = "/opt/dsh/container/dsh-task-broker.py"


def log(line):
    print(line, file=sys.stderr, flush=True)


def wait(seconds):
    compose.wait_for_admission(ADMISSION, deadline_seconds=seconds, stat=os.path.isfile, read_mtime=os.path.getmtime)


def read_downward():
    names = []
    for field in ("pod-name", "namespace"):
        names.append(read_fixed(IDENTITY_ROOT / field, 256).decode("ascii").strip())
    return tuple(names)


def build_observer_for(**kwargs):
    return compose.build_observer(unique_json=unique_json, requester_factory=ProtectedQualificationRequester,
                                  api_factory=FixedQualificationReadAPI, identity_factory=ExecutingPodIdentity,
                                  observer_factory=OfficialSDKDeploymentObserver, **kwargs)


def read_node_name(observer, *, namespace, pod_name, excluded):
    return compose.read_own_node_name(observer.read, namespace=namespace, pod_name=pod_name, excluded=excluded)


def load_providers():
    spec = importlib.util.find_spec("scripts.native_qualification_providers")
    if spec is None:
        return None
    return importlib.import_module("scripts.native_qualification_providers")


def load_broker():
    spec = importlib.util.spec_from_file_location("dsh_task_broker", BROKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # its __main__ block does not run
    return SimpleNamespace(REGISTRY=module.REGISTRY, WORKSPACE=module.WORKSPACE,
                           make_server=lambda: ThreadingHTTPServer((module.HOST, module.PORT), module.Handler))


def main():
    broker_holder = {}

    def broker_loader():
        broker_holder["broker"] = load_broker()
        return broker_holder["broker"]

    def configure_sdk(server, registry, observer):
        return configure_official_sdk(server, registry, os.environ.get("DSH_OFFICIAL_SDK_ADMISSION_FILE"),
                                      qualification_allowed=True, deployment_observer=observer,
                                      workspace_root=broker_holder["broker"].WORKSPACE)

    if sys.platform != "linux" or os.getuid() != 0:
        log("REFUSED LINUX_ROOT_REQUIRED")
        return compose.EXIT_REFUSED
    return compose.run_entry(env=dict(os.environ), wait=wait, read_admission=lambda: protected_bytes(ADMISSION, 65536),
                             read_downward=read_downward, build_observer_for=build_observer_for,
                             read_node_name=read_node_name, load_providers=load_providers, load_broker=broker_loader, configure_sdk=configure_sdk,
                             log=log)


if __name__ == "__main__":
    raise SystemExit(main())
