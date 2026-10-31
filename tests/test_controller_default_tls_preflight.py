import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("tls_preflight", ROOT / "scripts/controller_default_tls_preflight.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

class DefaultCertificateTests(unittest.TestCase):
    def setUp(self):
        self.pem = (ROOT / "tests/fixtures/controller-default-test-public.pem").read_bytes()
        self.settings = {"namespace":"llm","domain":"fixture.invalid","gatewayService":"gateway","tlsSecret":"unused-tls","runtimeImage":"registry.invalid/runtime@sha256:"+"a"*64,"apiCIDRs":["192.0.2.10/32"],"tlsMode":"controller-default","controllerDefaultTls":{"namespace":"kube-system","secretName":"default-tls","certificateSha256":hashlib.sha256(self.pem).hexdigest()}}
        self.args = ["--default-ssl-certificate=kube-system/default-tls"]
    def test_malformed_settings_and_argument_types_rejected(self):
        for bad_args in [self.args[0], None, [None]]:
            with self.assertRaisesRegex(ValueError,"list of strings"):
                MODULE.validate(self.settings,bad_args,self.pem)
        for bad_settings in [None, {"tlsMode":"controller-default"}, {**self.settings,"domain":"wrong/path"}, {**self.settings,"controllerDefaultTls":[]}]:
            with self.assertRaises(ValueError):
                MODULE.validate(bad_settings,self.args,self.pem)
        self.settings["controllerDefaultTls"]["certificateSha256"]="not-a-fingerprint"
        with self.assertRaisesRegex(ValueError,"fingerprint"):
            MODULE.validate(self.settings,self.args,self.pem)
    def test_actual_public_fixture_certificate_accepted(self):
        self.assertTrue(MODULE.validate(self.settings,self.args,self.pem)["publicCertificateOnly"])
    def test_changed_certificate_bytes_rejected(self):
        with self.assertRaisesRegex(ValueError,"bytes differ"):
            MODULE.validate(self.settings,self.args,self.pem+b"\n")
    def test_wrong_controller_secret_rejected(self):
        with self.assertRaisesRegex(ValueError,"reference differs"):
            MODULE.validate(self.settings,["--default-ssl-certificate=other/wrong"],self.pem)
    def test_uncovered_domain_rejected(self):
        self.settings["domain"]="other.invalid"
        with self.assertRaisesRegex(ValueError,"does not cover"):
            MODULE.validate(self.settings,self.args,self.pem)
    def test_expired_or_not_yet_valid_rejected(self):
        for clock in [0,4102444800]:
            with self.assertRaisesRegex(ValueError,"validity period"):
                MODULE.validate(self.settings,self.args,self.pem,now=clock)
    def test_mode_must_be_explicit(self):
        del self.settings["tlsMode"]
        with self.assertRaisesRegex(ValueError,"must be explicit"):
            MODULE.validate(self.settings,self.args,self.pem)
    def test_cli_refuses_unqualified_default_but_retains_force_https_when_qualified(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp);settings=folder/"settings.json";settings.write_text(json.dumps(self.settings));args=folder/"args.json";args.write_text(json.dumps(self.args));cert=folder/"public.pem";cert.write_bytes(self.pem);output=folder/"candidate.yaml"
            command=[sys.executable,str(ROOT/"scripts/render_app_hostname_support.py"),"--settings",str(settings),"--output",str(output)]
            denied=subprocess.run(command,capture_output=True)
            self.assertNotEqual(denied.returncode,0);self.assertFalse(output.exists())
            accepted=subprocess.run(command+["--controller-default-certificate",str(cert),"--controller-arguments",str(args)],capture_output=True)
            self.assertEqual(accepted.returncode,0,accepted.stderr.decode())
            import yaml
            route=list(yaml.safe_load_all(output.read_text()))[-1]
            self.assertNotIn("tls",route["spec"])
            self.assertEqual(route["metadata"]["annotations"]["nginx.ingress.kubernetes.io/force-ssl-redirect"],"true")
            self.assertEqual(route["metadata"]["annotations"]["nginx.ingress.kubernetes.io/proxy-read-timeout"],"3600")

if __name__ == "__main__":
    unittest.main()
