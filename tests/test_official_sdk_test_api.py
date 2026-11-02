"""Synthetic HTTPS/request fixtures only; no real identity, key load or network."""
import json
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from scripts import official_sdk_test_api as api


class APIReadTests(unittest.TestCase):
    def setUp(self):
        self.request = Mock()
        self.client = api.FixedQualificationReadAPI(self.request,
            namespace="dsh-sdk-test", pod_name="broker-pod", job_name="qualification")
    def test_exact_three_named_gets(self):
        cases = [("Namespace", "v1", None, "dsh-sdk-test", "/api/v1/namespaces/dsh-sdk-test"),
            ("Pod", "v1", "dsh-sdk-test", "broker-pod", "/api/v1/namespaces/dsh-sdk-test/pods/broker-pod"),
            ("Job", "batch/v1", "dsh-sdk-test", "qualification", "/apis/batch/v1/namespaces/dsh-sdk-test/jobs/qualification")]
        for kind, version, namespace, name, path in cases:
            value = {"kind": kind, "apiVersion": version, "metadata": {"name": name, "namespace": namespace}}
            self.request.return_value = (200, value)
            self.assertIs(self.client.read_resource(kind, version, namespace, name), value)
            self.request.assert_called_with("GET", path, None)
    def test_foreign_namespace_names_and_secret_access_never_reach_requester(self):
        for key in [("Pod", "v1", "production", "broker-pod"), ("Pod", "v1", "dsh-sdk-test", "other"),
                ("Secret", "v1", "dsh-sdk-test", "anything"), ("Job", "v1", "dsh-sdk-test", "qualification")]:
            with self.assertRaises(ValueError): self.client.read_resource(*key)
        self.request.assert_not_called()
    def test_http200_with_wrong_body_is_not_resource_evidence(self):
        self.request.return_value = (200, {"kind": "Pod", "apiVersion": "v1", "metadata": {"name": "other", "namespace": "dsh-sdk-test"}})
        with self.assertRaisesRegex(ValueError, "RESOURCE_MISMATCH"):
            self.client.read_resource("Pod", "v1", "dsh-sdk-test", "broker-pod")
    def test_404_does_not_become_absence(self):
        self.request.return_value = (404, {})
        with self.assertRaisesRegex(ValueError, "GET_FAILED"):
            self.client.read_resource("Pod", "v1", "dsh-sdk-test", "broker-pod")
        self.assertEqual(self.request.call_count, 1)
    def test_resource_name_path_escape_refused_before_request(self):
        for name in ("../secret", "pod?x=1", "pod/exec", "a..b", "a-", "a" * 254):
            with self.assertRaises(ValueError):
                api.FixedQualificationReadAPI(self.request, namespace="dsh-sdk-test", pod_name=name, job_name="qualification")
        self.request.assert_not_called()


class TLSRequesterTests(unittest.TestCase):
    def setUp(self):
        self.context = Mock()
        self.platform = patch.object(api.sys, "platform", "linux"); self.platform.start(); self.addCleanup(self.platform.stop)
        self.files = patch.object(api, "protected_identity_file"); self.check_files = self.files.start(); self.addCleanup(self.files.stop)
        self.ssl = patch.object(api.ssl, "SSLContext", return_value=self.context); self.ssl.start(); self.addCleanup(self.ssl.stop)
        self.requester = api.ProtectedQualificationRequester(namespace="dsh-sdk-test", pod_name="broker-pod", job_name="qualification")
        self.connection = Mock()
        self.network = patch.object(api.http.client, "HTTPSConnection", return_value=self.connection)
        self.connect = self.network.start(); self.addCleanup(self.network.stop)
        self.response = Mock(status=200)
        self.response.getheader.side_effect = lambda name, default="": {"Content-Type": "application/json", "Content-Encoding": "identity"}.get(name, default)
        self.response.read.return_value = b'{"kind":"Pod"}'
        self.connection.getresponse.return_value = self.response
    def call(self): return self.requester("GET", "/api/v1/namespaces/dsh-sdk-test/pods/broker-pod", None)
    def test_explicit_verified_tls_identity_and_no_password_prompt(self):
        self.assertEqual(self.context.verify_mode, api.ssl.CERT_REQUIRED)
        self.assertTrue(self.context.check_hostname)
        self.assertEqual(self.context.minimum_version, api.ssl.TLSVersion.TLSv1_2)
        self.check_files.assert_any_call(api.PRIVATE_KEY, private=True)
        password_callback = self.context.load_cert_chain.call_args.kwargs["password"]
        with self.assertRaisesRegex(ValueError, "NO_PROMPT"): password_callback()
    def test_exact_host_and_single_request_no_auth_header(self):
        self.assertEqual(self.call(), (200, {"kind": "Pod"}))
        self.connect.assert_called_once_with("kubernetes.default.svc", 443, context=self.context, timeout=3)
        self.connection.request.assert_called_once_with("GET", "/api/v1/namespaces/dsh-sdk-test/pods/broker-pod",
            headers={"Accept": "application/json", "Connection": "close"})
        self.connection.close.assert_called_once()
    def test_mutations_exec_and_secret_paths_refused_without_network(self):
        for method, path, body in [("DELETE", "/api/v1/namespaces/dsh-sdk-test/pods/broker-pod", None),
                ("GET", "/api/v1/namespaces/dsh-sdk-test/secrets/x", None),
                ("POST", "/api/v1/namespaces/dsh-sdk-test/pods/broker-pod/exec", None),
                ("GET", "/api/v1/namespaces/dsh-sdk-test/pods/broker-pod", {})]:
            with self.assertRaises(ValueError): self.requester(method, path, body)
        self.connect.assert_not_called()
    def test_redirect_and_failures_do_not_retry(self):
        for status in (301, 401, 403, 404, 500):
            self.response.status = status
            with self.assertRaisesRegex(ValueError, "GET_FAILED"): self.call()
        self.assertEqual(self.connection.request.call_count, 5)
        self.assertEqual(self.connection.close.call_count, 5)
    def test_duplicate_json_refused(self):
        self.response.read.return_value = b'{"kind":"Pod","kind":"Secret"}'
        with self.assertRaisesRegex(ValueError, "DUPLICATE"): self.call()
        self.connection.close.assert_called_once()
    def test_oversize_encoding_and_non_json_refused(self):
        self.response.read.return_value = b"x" * (api.MAX_RESPONSE + 1)
        with self.assertRaisesRegex(ValueError, "TOO_LARGE"): self.call()
        self.response.getheader.side_effect = lambda name, default="": "text/html" if name == "Content-Type" else default
        with self.assertRaisesRegex(ValueError, "JSON_REQUIRED"): self.call()
    def test_timeout_closed_without_retry(self):
        self.connection.request.side_effect = TimeoutError("synthetic")
        with self.assertRaises(TimeoutError): self.call()
        self.connection.request.assert_called_once(); self.connection.close.assert_called_once()
    def test_missing_identity_refuses_before_network(self):
        self.check_files.side_effect = ValueError("missing protected fixture")
        with self.assertRaises(ValueError): api.ProtectedQualificationRequester(namespace="dsh-sdk-test", pod_name="broker-pod", job_name="qualification")
        self.connect.assert_not_called()
    def test_non_linux_refuses_before_identity_or_network(self):
        self.check_files.reset_mock()
        with patch.object(api.sys, "platform", "win32"):
            with self.assertRaisesRegex(ValueError, "REQUIRES_LINUX"):
                api.ProtectedQualificationRequester(namespace="dsh-sdk-test", pod_name="broker-pod", job_name="qualification")
        self.check_files.assert_not_called(); self.connect.assert_not_called()
    def test_compressed_body_is_not_silently_expanded(self):
        self.response.getheader.side_effect = lambda name, default="": {
            "Content-Type": "application/json", "Content-Encoding": "gzip"}.get(name, default)
        with self.assertRaisesRegex(ValueError, "ENCODING_REFUSED"): self.call()
        self.response.read.assert_not_called()


class ProtectedFileTests(unittest.TestCase):
    def fixture(self, mode=stat.S_IFREG | 0o600, uid=0, parents=()):
        return SimpleNamespace(parents=parents, lstat=lambda: SimpleNamespace(st_mode=mode, st_uid=uid))
    def test_symlink_untrusted_owner_and_writable_ancestor_refused(self):
        for path in (self.fixture(stat.S_IFLNK | 0o777), self.fixture(uid=10001),
                self.fixture(parents=[self.fixture(stat.S_IFDIR | 0o777)])):
            with self.assertRaisesRegex(ValueError, "UNPROTECTED"):
                api.protected_identity_file(path, private=True)
    def test_private_key_world_readable_refused(self):
        with self.assertRaisesRegex(ValueError, "UNPROTECTED"):
            api.protected_identity_file(self.fixture(stat.S_IFREG | 0o644), private=True)
        api.protected_identity_file(self.fixture(), private=True)


if __name__ == "__main__": unittest.main()
