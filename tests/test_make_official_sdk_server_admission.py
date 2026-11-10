"""The server admission minter: what it returns is accepted by the REAL configure(); every drift is refused. No cluster, no credential."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts import make_official_sdk_server_admission as minter
from scripts import official_sdk_bootstrap as bootstrap

BINDING = {"namespace": "dsh-a2a-qual", "namespaceUID": "11111111-1111-1111-1111-111111111111",
           "podUID": "22222222-2222-2222-2222-222222222222", "workloadUID": "33333333-3333-3333-3333-333333333333"}
DIGEST = "sha256:" + "a" * 64
COMMIT = "c" * 40
NOW = 1_800_000_000
PACKAGE = (json.dumps({"kind": "DSH_OFFICIAL_SDK_PACKAGE_V1", "sourceCommit": COMMIT, "sdkVersion": "0.2.2a2", "runtimeVersion": "0.2.2a2",
                       "sdkWheelSha256": "e" * 64, "installedRecordSha256": "f" * 64}, sort_keys=True) + "\n").encode()


def fake_reader(extra=None):
    """A synthetic /opt/dsh tree: every role file exists with distinct bytes."""
    files = {path: ("source of " + path).encode() for path in bootstrap.SOURCES.values()}
    files[minter.SCOPE_MODULE] = files.get(minter.SCOPE_MODULE, b"scope")
    files.update(extra or {})

    def read(path, limit=1024 * 1024):
        if path not in files:
            raise minter.MintRefused("SOURCE_MISSING:" + path)
        return files[path]
    return read, files


def mint(**override):
    read, _ = fake_reader()
    values = dict(read_source=read, source_commit=COMMIT, image_digest=DIGEST, package_admission_raw=PACKAGE, subject="qualification-broker",
                  generation="gen-1", binding=BINDING, now=NOW)
    values.update(override)
    return minter.mint(**values)


class MinterTests(unittest.TestCase):
    def test_descriptor_has_the_exact_key_set_a_default_window_and_every_source_role(self):
        raw, d = mint()
        self.assertEqual(set(d), {"kind", "mode", "subject", "generation", "expiresAt", "sourceCommit", "imageDigest", "packageAdmissionSha256", "scopeModule",
                                  "scopeSha256", "sources", "deploymentBinding"})
        self.assertEqual(d["expiresAt"], NOW + 270)
        self.assertEqual(set(d["sources"]), set(bootstrap.SOURCES))   # all 45 roles, read from the module (a role added later is covered)
        self.assertEqual(len(d["sources"]), len(bootstrap.SOURCES))
        self.assertEqual(d["packageAdmissionSha256"], hashlib.sha256(PACKAGE).hexdigest())
        self.assertEqual(d["deploymentBinding"], dict(BINDING, environment="test", workloadRole="qualification"))
        self.assertEqual(json.loads(raw), d)

    def test_a_changed_source_changes_only_its_own_hash_and_an_added_role_is_hashed(self):
        read, files = fake_reader()
        _, base = mint(read_source=read)
        role, path = next(iter(bootstrap.SOURCES.items()))
        read2, _ = fake_reader({path: b"changed"})
        _, changed = mint(read_source=read2)
        diffs = [r for r in base["sources"] if base["sources"][r] != changed["sources"][r]]
        self.assertEqual(diffs, [role] if path != minter.SCOPE_MODULE else diffs)
        original = dict(bootstrap.SOURCES)
        try:
            bootstrap.SOURCES["qualificationEntry"] = "/opt/dsh/container/dsh-native-qualification-broker.py"
            read3, _ = fake_reader({"/opt/dsh/container/dsh-native-qualification-broker.py": b"entry"})
            _, with_entry = mint(read_source=read3)
            self.assertIn("qualificationEntry", with_entry["sources"])
        finally:
            bootstrap.SOURCES.clear()
            bootstrap.SOURCES.update(original)

    def test_real_configure_refuses_what_the_minter_would_never_emit(self):
        read, _ = fake_reader()
        raw, d = mint()
        for label, change in (("window above 300", lambda v: v.update(expiresAt=NOW + 301)), ("expired", lambda v: v.update(expiresAt=NOW - 1)),
                              ("non-test environment", lambda v: v["deploymentBinding"].update(environment="production")),
                              ("extra key", lambda v: v.update(extra=1)), ("bad scope hash", lambda v: v.update(scopeSha256="0" * 63 + "g"))):
            with self.subTest(label):
                broken = copy.deepcopy(d)
                change(broken)
                with self.assertRaises(minter.MintRefused):
                    minter.selfcheck((json.dumps(broken, sort_keys=True) + "\n").encode(), read_source=read, package_admission_raw=PACKAGE, binding=BINDING, now=NOW)
        # a wrong observed deployment is refused too
        with self.assertRaises(minter.MintRefused):
            minter.selfcheck(raw, read_source=read, package_admission_raw=PACKAGE, binding=dict(BINDING, podUID="44444444-4444-4444-4444-444444444444"), now=NOW)

    def test_the_window_is_bounded_and_skew_margin_is_the_default(self):
        _, d = mint(ttl=295)
        self.assertEqual(d["expiresAt"], NOW + 295)   # allowed, but a Pod clock more than 5 s behind the minting clock then makes configure() refuse it
        for ttl in (0, 296, -1, 270.5):
            with self.assertRaisesRegex(minter.MintRefused, "TTL_1_TO_295_REQUIRED"):
                mint(ttl=ttl)

    def test_input_refusals(self):
        for override, code in ((dict(source_commit="short"), "SOURCE_COMMIT_REQUIRED"), (dict(image_digest="sha256:" + "0" * 64), "IMAGE_DIGEST_REQUIRED"),
                               (dict(image_digest="registry/x:latest"), "IMAGE_DIGEST_REQUIRED"), (dict(subject=""), "INVALID_SUBJECT"),
                               (dict(binding=dict(BINDING, podUID="nope")), "BINDING_UIDS_REQUIRED"),
                               (dict(binding=dict(BINDING, namespace="dsh-openshell-test-20261102")), "A2A_OWNED_TEST_NAMESPACE_REQUIRED"),
                               (dict(binding={"namespace": "dsh-a2a-x"}), "BINDING_KEYS"),
                               (dict(package_admission_raw=b'{"kind": "other"}'), "PACKAGE_ADMISSION_KIND")):
            with self.subTest(code):
                with self.assertRaisesRegex(minter.MintRefused, code):
                    mint(**override)

    def test_a_missing_source_file_is_refused_not_skipped(self):
        files = {p: b"x" for p in bootstrap.SOURCES.values()}
        files.pop(next(iter(bootstrap.SOURCES.values())))
        with self.assertRaises(minter.MintRefused):
            mint(read_source=lambda path, limit=1024 * 1024: files[path] if path in files else (_ for _ in ()).throw(minter.MintRefused("SOURCE_MISSING:" + path)))

    def test_tree_reader_maps_opt_dsh_to_a_checkout_and_refuses_escapes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "scripts").mkdir()
            (root / "scripts" / "x.py").write_bytes(b"x")
            read = minter.tree_reader(root)
            self.assertEqual(read("/opt/dsh/scripts/x.py"), b"x")
            for bad in ("/etc/passwd", "/opt/dsh/../x", "/opt/dsh/scripts/missing.py"):
                with self.assertRaises(minter.MintRefused):
                    read(bad)

    def test_the_real_tree_has_every_role_and_a_descriptor_minted_from_it_is_accepted_by_the_real_configure(self):
        """With the guard sidecar and the entry point in the tree (A2A lane, P1 step 2) every protected role resolves to a real file. The
        descriptor is minted from the repository's OWN files (the image copies this tree to /opt/dsh) and the real configure() accepts it."""
        dsh_root = Path(minter.__file__).resolve().parents[1]
        read = minter.tree_reader(dsh_root)
        missing = []
        for role, path in bootstrap.SOURCES.items():
            try:
                read(path)
            except minter.MintRefused:
                missing.append(role)
        self.assertEqual(missing, [], "protected roles without a file in the tree")
        self.assertGreaterEqual(len(bootstrap.SOURCES), 47)
        raw, d = mint(read_source=read)
        self.assertEqual(set(d["sources"]), set(bootstrap.SOURCES))
        for role in ("qualificationEntry", "nativeComposition", "modelGuardSidecar"):
            self.assertIn(role, d["sources"])
        for role, path in bootstrap.SOURCES.items():
            self.assertEqual(d["sources"][role], hashlib.sha256(read(path)).hexdigest())


if __name__ == "__main__":
    unittest.main()
