"""Inputs of the D10 (b) provider runtime: policy, lease reader, rollback recorder, operator-delivered provider rows.
Fake protected reader; the rows route is also run through the REAL TaskProviderCapture fixture of test_a2a_provider_capture."""
import copy
import json
import unittest
import uuid

from scripts import native_qualification_inputs as inputs
from scripts.a2a_provider_capture import TaskProviderCapture
from scripts.official_sdk_package_admission import unique_json

POLICY = {"claim": "dsh-a2a-qual-workspace", "subpath": "qual", "writes": False, "brokerPath": "/workspace",
          "credentialSecret": "dsh-a2a-qual-task-credential"}


class Files:
    def __init__(self, files):
        self.files, self.calls = files, []

    def __call__(self, path, limit):
        self.calls.append(path)
        if path not in self.files:
            raise FileNotFoundError(path)
        raw = self.files[path]
        raw = raw if isinstance(raw, bytes) else json.dumps(raw).encode()
        if len(raw) > limit:
            raise ValueError("TOO_LARGE")
        return raw


class WorkspacePolicyTests(unittest.TestCase):
    def lookup(self, doc):
        reader = Files({inputs.WORKSPACE_POLICY_FILE: doc})
        return inputs.workspace_policy_lookup(reader=reader, unique_json=unique_json), reader

    def test_the_admitted_project_returns_a_copy_and_the_file_is_reread_each_time(self):
        look, reader = self.lookup({"policies": {".": POLICY}})
        first = look("owner", ".")
        self.assertEqual(first, POLICY)
        first["claim"] = "mutated"
        self.assertEqual(look("owner", ".")["claim"], "dsh-a2a-qual-workspace")
        self.assertEqual(len(reader.calls), 2)

    def test_unknown_project_and_malformed_policies_are_refused(self):
        look, _ = self.lookup({"policies": {".": POLICY}})
        with self.assertRaisesRegex(ValueError, "WORKSPACE_PROJECT_NOT_ADMITTED"):
            look("owner", "other")
        for field, value in (("claim", "Bad_Name"), ("credentialSecret", ""), ("subpath", ".."), ("subpath", "a/b"),
                             ("writes", "false"), ("brokerPath", "/etc"), ("brokerPath", "/workspace/../x"),
                             ("brokerPath", "workspace")):
            with self.subTest(field=field, value=value):
                look, _ = self.lookup({"policies": {".": {**POLICY, field: value}}})
                with self.assertRaisesRegex(ValueError, "EXACT_ADMITTED_WORKSPACE_POLICY_REQUIRED"):
                    look("owner", ".")
        for doc in ({"policies": {".": {**POLICY, "extra": 1}}}, {"policies": {".": {k: v for k, v in POLICY.items() if k != "claim"}}},
                    {"policies": [], "x": 1}, {"other": {}}):
            with self.subTest(doc=str(doc)[:40]):
                look, _ = self.lookup(doc)
                with self.assertRaises(ValueError):
                    look("owner", ".")

    def test_the_policy_is_compatible_with_what_the_factory_demands(self):
        # exactly the five keys a2a_factory_contract checks
        self.assertEqual(set(POLICY), {"claim", "subpath", "writes", "brokerPath", "credentialSecret"})
        self.assertEqual(set(inputs.POLICY_KEYS), set(POLICY))


class LeaseAndRollbackTests(unittest.TestCase):
    def test_lease_reader_returns_the_object_and_refuses_a_list(self):
        reader = Files({inputs.LEASE_FILE: {"subject": "owner"}})
        self.assertEqual(inputs.lease_reader(reader=reader, unique_json=unique_json)(), {"subject": "owner"})
        bad = Files({inputs.LEASE_FILE: []})
        with self.assertRaisesRegex(ValueError, "EXECUTION_LEASE_OBJECT_REQUIRED"):
            inputs.lease_reader(reader=bad, unique_json=unique_json)()
        with self.assertRaises(FileNotFoundError):
            inputs.lease_reader(reader=Files({}), unique_json=unique_json)()

    def test_rollback_is_a_recorder_that_claims_nothing(self):
        recorder = inputs.RollbackRecorder()
        out = recorder(object(), {"taskId": "a" * 32, "correlationId": "b" * 32})
        self.assertEqual((out["kind"], out["mutations"], out["rollbackVerified"], out["providerExecutionStoppedVerified"]),
                         (inputs.RECORD_KIND, 0, False, False))
        self.assertEqual(len(recorder.records), 1)
        with self.assertRaisesRegex(ValueError, "EXACT_ROLLBACK_TASK_BINDING_REQUIRED"):
            recorder(object(), {"taskId": "x"})


class RowsRouteTests(unittest.TestCase):
    def setUp(self):
        self.ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        self.rows = [dict(request_id="chatcmpl-1", litellm_call_id=self.ids[0], model="deepseek-v4.1-flash",
                          status="success", prompt_tokens=5, completion_tokens=2)]
        self.source = dict(sourceCommit="a" * 40, imageDigest="sha256:" + "e" * 64, exporterSha256="b" * 64)

    def query(self, rows):
        reader = Files({inputs.PROVIDER_ROWS_FILE: rows})
        return inputs.RowsFileProviderQuery(reader=reader, unique_json=unique_json, source_observer=lambda: copy.deepcopy(self.source))

    def test_only_rows_of_admitted_call_ids_are_returned_with_the_exact_envelope(self):
        foreign = dict(self.rows[0], litellm_call_id=str(uuid.uuid4()), request_id="chatcmpl-x")
        request = {"operationIds": [self.ids[0]], "kind": "q"}
        out = self.query([foreign] + self.rows)(request)
        self.assertEqual(set(out), {"query", "source", "rows"})
        self.assertEqual(out["rows"], self.rows)
        self.assertEqual(out["query"], request)
        self.assertEqual(out["source"], self.source)

    def test_missing_rows_are_not_invented_and_a_bad_selector_is_refused(self):
        out = self.query([])({"operationIds": [self.ids[0]]})
        self.assertEqual(out["rows"], [])
        for selector in (None, [], [self.ids[0]] * 2, ["not-a-uuid"], [self.ids[0], self.ids[1], str(uuid.uuid4())], "x"):
            with self.subTest(selector=selector), self.assertRaisesRegex(ValueError, "EXACT_ADMITTED_OPERATION_SELECTOR_REQUIRED"):
                self.query(self.rows)({"operationIds": selector})

    def test_source_binding_hashes_this_module_and_needs_an_observer(self):
        reader = Files({inputs.MODULE_FILE: b"module bytes"})
        binding = inputs.provider_source_binding(reader=reader, source_commit="a" * 40, image_digest="sha256:" + "e" * 64)
        import hashlib
        self.assertEqual(binding["exporterSha256"], hashlib.sha256(b"module bytes").hexdigest())
        with self.assertRaises(ValueError):
            inputs.RowsFileProviderQuery(reader=reader, unique_json=unique_json, source_observer=None)

    def test_the_route_satisfies_the_real_task_provider_capture(self):
        from test_a2a_provider_capture import ProviderCaptureTests
        case = ProviderCaptureTests("test_construction_is_inert_and_capture_retains_only_exact_metadata_once")
        case.setUp()
        try:
            case.guard()
            reader = Files({inputs.PROVIDER_ROWS_FILE: [dict(case.row)], inputs.MODULE_FILE: b"module"})
            binding = inputs.provider_source_binding(reader=reader, source_commit="a" * 40, image_digest="sha256:" + "e" * 64)
            query = inputs.RowsFileProviderQuery(reader=reader, unique_json=unique_json, source_observer=lambda: copy.deepcopy(binding))
            capture = TaskProviderCapture(controller=case.f.controller, generation="g1", query_metadata=query,
                                          source_observer=lambda: copy.deepcopy(binding), source_binding=binding)
            result = capture(case.task, case.binding)
            self.assertTrue(result["queryExecuted"])
            self.assertEqual(result["matchedOperationCount"], 1)
            self.assertTrue(result["providerMetadataIdentityMatched"])
        finally:
            case.doCleanups()

    def test_an_undelivered_row_makes_the_real_capture_refuse(self):
        from test_a2a_provider_capture import ProviderCaptureTests
        case = ProviderCaptureTests("test_construction_is_inert_and_capture_retains_only_exact_metadata_once")
        case.setUp()
        try:
            case.guard()
            reader = Files({inputs.PROVIDER_ROWS_FILE: [], inputs.MODULE_FILE: b"module"})
            binding = inputs.provider_source_binding(reader=reader, source_commit="a" * 40, image_digest="sha256:" + "e" * 64)
            query = inputs.RowsFileProviderQuery(reader=reader, unique_json=unique_json, source_observer=lambda: copy.deepcopy(binding))
            capture = TaskProviderCapture(controller=case.f.controller, generation="g1", query_metadata=query,
                                          source_observer=lambda: copy.deepcopy(binding), source_binding=binding)
            with self.assertRaises(ValueError):
                capture(case.task, case.binding)
        finally:
            case.doCleanups()


class ExecutionAdmissionTests(unittest.TestCase):
    NS_UID = "11111111-1111-4111-8111-111111111111"

    def setUp(self):
        self.now = 1000.0
        self.values = dict(subject="owner", namespace="dsh-a2a-qual", namespaceUID=self.NS_UID,
                           image="registry.invalid/image@sha256:" + "a" * 64, sourceCommit="b" * 40, nodeName="node-1")
        self.lease = dict(self.values, expiresAt=1200.0, modelStartsAllowed=1)
        self.admit = inputs.make_execution_admission(controller_values=self.values, lease_reader=lambda: copy.deepcopy(self.lease),
                                                      clock=lambda: self.now)

    def controller(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from scripts.a2a_worker_controller import WorkerController
        api = SimpleNamespace(namespace="dsh-a2a-qual", namespace_uid=self.NS_UID)
        return WorkerController(api=api, subject="owner", image=self.values["image"], source_commit="b" * 40, node_name="node-1",
                                project_admission=Mock(), execution_admission=self.admit, clock=lambda: self.now)

    def task(self):
        from types import SimpleNamespace
        return SimpleNamespace(id="a" * 32, correlation_id="b" * 32,
                               request=dict(project=".", runtime="claude", writes=False, prompt="synthetic"),
                               a2a_cli_worker=None)

    def test_the_real_worker_controller_accepts_the_projected_admission(self):
        value = self.controller()._execution(self.task(), model=True)
        self.assertEqual((value["mode"], value["modelStartsAllowed"], value["expiresAt"]), ("private-test", 1, 1200.0))

    def test_a_lease_without_a_start_gives_zero_and_a_model_start_is_then_refused_by_the_controller(self):
        self.lease["modelStartsAllowed"] = 0
        self.assertEqual(self.controller()._execution(self.task())["modelStartsAllowed"], 0)
        with self.assertRaisesRegex(ValueError, "FRESH_PRIVATE_WORKER_EXECUTION_ADMISSION_REQUIRED"):
            self.controller()._execution(self.task(), model=True)

    def test_up_to_three_lease_starts_still_project_to_one_per_task(self):
        self.lease["modelStartsAllowed"] = 3
        self.assertEqual(self.controller()._execution(self.task(), model=True)["modelStartsAllowed"], 1)

    def test_foreign_expired_too_long_or_malformed_leases_are_refused(self):
        for key, value in (("nodeName", "other"), ("image", "x"), ("namespaceUID", "z"), ("subject", "intruder")):
            with self.subTest(key=key):
                self.setUp()
                self.lease[key] = value
                with self.assertRaisesRegex(ValueError, "EXECUTION_LEASE_FOREIGN_OR_STALE"):
                    self.controller()._execution(self.task())
        for expires in (999.0, 1000.0, 1301.0, True, "1200"):
            with self.subTest(expires=expires):
                self.setUp()
                self.lease["expiresAt"] = expires
                with self.assertRaisesRegex(ValueError, "EXECUTION_LEASE_EXPIRED_OR_TOO_LONG"):
                    self.controller()._execution(self.task())
        for starts in (-1, 4, True, "1", None):
            with self.subTest(starts=starts):
                self.setUp()
                self.lease["modelStartsAllowed"] = starts
                with self.assertRaisesRegex(ValueError, "EXECUTION_LEASE_MODEL_STARTS_INVALID"):
                    self.controller()._execution(self.task())

    def test_the_controller_values_must_be_exact_strings(self):
        for key in inputs.LEASE_BOUND:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "EXACT_CONTROLLER_VALUES_REQUIRED"):
                inputs.make_execution_admission(controller_values={**self.values, key: ""}, lease_reader=lambda: {})


class RowsDirectoryTests(unittest.TestCase):
    A, B = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"

    def query(self, files):
        def reader(path, limit):
            if path not in files:
                raise OSError("missing")
            return json.dumps(files[path]).encode()
        return inputs.RowsDirectoryProviderQuery(reader=reader, unique_json=lambda raw: json.loads(raw.decode()),
                                                 source_observer=lambda: {"k": 1}, directory="/d")

    def test_each_admitted_call_reads_only_its_own_file(self):
        row = {"litellm_call_id": self.A, "status": "success"}
        out = self.query({"/d/" + self.A + ".json": row, "/d/" + self.B + ".json": {"litellm_call_id": self.B}})(
            {"operationIds": [self.A]})
        self.assertEqual(out["rows"], [row])
        self.assertEqual(set(out), {"query", "source", "rows"})

    def test_a_missing_unreadable_or_misnamed_file_gives_no_row(self):
        q = self.query({"/d/" + self.B + ".json": {"litellm_call_id": self.A}})
        self.assertEqual(q({"operationIds": [self.A, self.B]})["rows"], [])

    def test_selector_validation_is_the_same_as_the_file_variant(self):
        for ids in ([], ["x"], [self.A, self.A], [self.A, self.B, self.A], None):
            with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, "EXACT_ADMITTED_OPERATION_SELECTOR_REQUIRED"):
                self.query({})({"operationIds": ids})


if __name__ == "__main__":
    unittest.main()
