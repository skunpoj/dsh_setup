"""Synthetic pre-image receipts; no packages, images or providers are executed."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import test_official_sdk_release_admission as fixtures
from scripts.official_sdk_release_admission import (
    SOURCE_TREE, PNPM_LOCK_SHA256, verify_producer_pair, verify_release_pair,
)
from scripts.produce_official_sdk_pair import (
    Producer, VERIFIER_PATH, digest_file, load_bound_verifier, require_plain_ancestors,
    validate_admission, verify_cache, read_plain_file, verify_bounded_workspace,
)


def producer_admission(root):
    return {
        "kind":"DSH_SDK_PRODUCER_ADMISSION_V1", "operationId":"a"*32,
        "expiresAt":2000, "sourceCommit":fixtures.SOURCE,
        "sourceTree":SOURCE_TREE, "pnpmLockSha256":PNPM_LOCK_SHA256,
        "builderImage":"registry.example/builder@sha256:"+"1"*64,
        "manylinuxImage":"registry.example/manylinux@sha256:"+"2"*64,
        "cacheRoot":str(root/"cache"), "cacheManifest":str(root/"cache.json"),
        "cacheManifestSha256":"3"*64, "caFile":str(root/"ca.pem"),
        "caSha256":"4"*64, "workRoot":str(root/"work"),
        "minimumFreeBytes":1024, "producerSha256":"5"*64,
        "verifierSha256":digest_file(VERIFIER_PATH),
        "stageHashes":{"prepare.sh":"6"*64,"manylinux.sh":"7"*64,
                       "compile.sh":"8"*64,"keyless_approval.py":"9"*64},
        "resourceLimits":{"nanoCpus":2_000_000_000,"memoryBytes":2*1024**3,
                          "pidsLimit":256,"storageBytes":8*1024**3},
    }


class FakeDocker:
    def __init__(self, admission, *, uncertain=False, foreign=False, cleanup_failure=False):
        self.a=admission; self.uncertain=uncertain; self.foreign=foreign
        self.cleanup_failure=cleanup_failure; self.calls=[]; self.cid="b"*64
        self.created=False; self.removed=False; self.missing_reads=0; self.lie_remove=False; self.never_appears=False

    def info(self):
        limits=self.a["resourceLimits"]
        return {"Id":self.cid,"Config":{"Image":self.a["builderImage"],
                "Labels":{"dsh.sdk.operation":("f"*32 if self.foreign else self.a["operationId"])}},
                "HostConfig":{"NetworkMode":"none","NanoCpus":limits["nanoCpus"],
                "Memory":limits["memoryBytes"],"MemorySwap":limits["memoryBytes"],
                "PidsLimit":limits["pidsLimit"],"StorageOpt":{"size":str(limits["storageBytes"])}},
                "State":{"Running":False,"ExitCode":0}}

    def __call__(self, args, **kwargs):
        self.calls.append(tuple(args))
        if args[:2]==["docker","inspect"]:
            identity=args[2]
            if not self.created or self.removed or self.never_appears or self.missing_reads:
                if self.created and self.missing_reads: self.missing_reads-=1
                return SimpleNamespace(returncode=1,stdout=b"",stderr=("Error: No such object: "+identity).encode())
            return SimpleNamespace(returncode=0,stdout=json.dumps([self.info()]).encode(),stderr=b"")
        if args[:2]==["docker","create"]:
            self.created=True
            if self.uncertain:
                raise subprocess.TimeoutExpired(args,1)
            return SimpleNamespace(returncode=0,stdout=(self.cid+"\n").encode(),stderr=b"")
        if args[:2]==["docker","start"]:
            return SimpleNamespace(returncode=0,stdout=b"",stderr=b"")
        if args[:2]==["docker","rm"]:
            if self.cleanup_failure:
                return SimpleNamespace(returncode=1,stdout=b"",stderr=b"failed")
            self.removed=not self.lie_remove
            return SimpleNamespace(returncode=0,stdout=b"",stderr=b"")
        return SimpleNamespace(returncode=0,stdout=b"",stderr=b"")


class ProducerReceiptTests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.ReleaseAdmissionTests()
        fixture.setUp()
        self.sdk, self.runtime = fixture.sdk, fixture.runtime
        self.receipt = {key: value for key, value in fixture.receipt.items()
                        if key != "applicationImage"}
        self.receipt.update(kind="DSH_OFFICIAL_SDK_PRODUCER_V1", sourceTree=SOURCE_TREE,
            pnpmLockSha256=PNPM_LOCK_SHA256, manylinuxImage="registry.example/manylinux@sha256:" + "3" * 64,
            nodeVersion="v24.9.0", pnpmVersion="11.28.5", uvVersion="0.11.23", operationId="a" * 32)

    def verify(self, **changes):
        raw = json.dumps({**self.receipt, **changes}).encode()
        return verify_producer_pair(receipt_raw=raw, trusted_receipt_sha256=hashlib.sha256(raw).hexdigest(),
                                   sdk_raw=self.sdk, runtime_raw=self.runtime)

    def test_preimage_output_has_no_fictitious_application_image(self):
        result = self.verify()
        self.assertEqual(result["kind"], "DSH_OFFICIAL_SDK_PRODUCER_VERIFIED_V1")
        self.assertFalse(result["applicationImageBound"])
        self.assertNotIn("applicationImage", result)
        self.assertNotIn("admitted", result)
        self.assertEqual(result["sourceTree"], SOURCE_TREE)

    def test_application_image_cannot_be_smuggled_into_producer_receipt(self):
        with self.assertRaisesRegex(ValueError, "INVALID_RELEASE_RECEIPT"):
            self.verify(applicationImage="registry.example/not-yet-built@sha256:" + "4" * 64)

    def test_source_tree_lock_and_toolchain_are_bound(self):
        for change in ({"sourceTree": "f" * 40}, {"pnpmLockSha256": "f" * 64},
                       {"nodeVersion": "v22.20.0"}, {"nodeVersion": "v24.8.0"},
                       {"nodeVersion": "v25.0.0"}, {"pnpmVersion": "11.28.4"},
                       {"uvVersion": "0.11.22"}, {"operationId": "0" * 32}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "BUILD_BINDING"):
                self.verify(**change)

    def test_images_require_actual_nonzero_digest(self):
        for change in ({"builderImage": "registry.example/builder:latest"},
                       {"builderImage": "registry.example/builder@sha256:" + "0" * 64},
                       {"manylinuxImage": "registry.example/manylinux:latest"},
                       {"manylinuxImage": "registry.example/manylinux@sha256:" + "0" * 64}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.verify(**change)

    def test_receipt_is_not_accepted_as_final_image_release(self):
        raw = json.dumps(self.receipt).encode()
        with self.assertRaises(ValueError):
            verify_release_pair(receipt_raw=raw, trusted_receipt_sha256=hashlib.sha256(raw).hexdigest(),
                                sdk_raw=self.sdk, runtime_raw=self.runtime)

    def test_producer_still_verifies_actual_wheel_bytes(self):
        self.runtime += b"changed"
        with self.assertRaises(ValueError): self.verify()

    def test_parent_cannot_trust_an_unapproved_receipt_hash(self):
        raw = json.dumps(self.receipt).encode()
        with self.assertRaisesRegex(ValueError, "UNTRUSTED_RELEASE_RECEIPT"):
            verify_producer_pair(receipt_raw=raw, trusted_receipt_sha256="f" * 64,
                                sdk_raw=self.sdk, runtime_raw=self.runtime)


class ProducerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.a=producer_admission(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def make(self, fake):
        producer=Producer(self.a,run=fake,clock=lambda:1000)
        producer.root.mkdir()
        (producer.root/"out").mkdir()
        (producer.root/"host-home").mkdir()
        producer.owns_root=True
        return producer

    def test_admission_binds_verifier_and_exact_resource_limits(self):
        self.assertEqual(validate_admission(self.a,now=1000)["verifierSha256"],digest_file(VERIFIER_PATH))
        for change in ({"verifierSha256":"0"*64},
                       {"resourceLimits":{"nanoCpus":0,"memoryBytes":2*1024**3,
                         "pidsLimit":256,"storageBytes":8*1024**3}},
                       {"resourceLimits":{"nanoCpus":2_000_000_000,"memoryBytes":2*1024**3,
                         "pidsLimit":0,"storageBytes":8*1024**3}}):
            value={**self.a,**change}
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_admission(value,now=1000)

    def test_verifier_hash_is_checked_before_module_loading(self):
        with mock.patch("scripts.produce_official_sdk_pair.types.ModuleType") as loader, \
             self.assertRaisesRegex(ValueError,"PRODUCER_VERIFIER_CHANGED"):
            load_bound_verifier("f"*64)
        loader.assert_not_called()
        module=load_bound_verifier(digest_file(VERIFIER_PATH))
        self.assertEqual(module.SOURCE,fixtures.SOURCE)

    def test_cache_refuses_unmanifested_fifo(self):
        cache=self.root/"cache"; cache.mkdir()
        for name in ("pnpm-store","node-gyp","python-wheels","pkg-cache"):
            (cache/name).mkdir()
            (cache/name/"x").write_bytes(name.encode())
        files=[]
        for path in cache.rglob("x"):
            files.append({"path":path.relative_to(cache).as_posix(),"bytes":path.stat().st_size,
                          "sha256":digest_file(path)})
        manifest=json.dumps({"kind":"DSH_OFFLINE_SDK_CACHE_V1","files":files}).encode()
        actual=list(cache.rglob("*")); pipe=cache/"pnpm-store"/"pipe"
        original_lstat=os.lstat
        def fake_lstat(path,*args,**kwargs):
            if Path(path)==pipe:
                return SimpleNamespace(st_mode=stat.S_IFIFO|0o600)
            return original_lstat(path,*args,**kwargs)
        with mock.patch.object(Path,"rglob",return_value=[*actual,pipe]), \
             mock.patch("scripts.produce_official_sdk_pair.os.lstat",side_effect=fake_lstat), \
             self.assertRaisesRegex(ValueError,"CACHE_SPECIAL_FILE_REFUSED"):
            verify_cache(cache,manifest)

    def test_symlinked_ancestor_is_refused(self):
        target=self.root/"cache"
        original_lstat=os.lstat
        def fake_lstat(path,*args,**kwargs):
            if Path(path)==self.root:
                return SimpleNamespace(st_mode=stat.S_IFLNK|0o777)
            return original_lstat(path,*args,**kwargs)
        with mock.patch("scripts.produce_official_sdk_pair.os.lstat",side_effect=fake_lstat), \
             self.assertRaisesRegex(ValueError,"PRODUCER_PATH_SYMLINK_REFUSED"):
            require_plain_ancestors(target,leaf_may_be_missing=True)

    def test_container_has_all_resource_limits_and_single_create(self):
        fake=FakeDocker(self.a); producer=self.make(fake)
        producer.container("prepare",self.a["builderImage"],"prepare.sh")
        creates=[call for call in fake.calls if call[:2]==("docker","create")]
        self.assertEqual(len(creates),1)
        args=creates[0]
        for expected in ("--cpus","--memory","--memory-swap","--pids-limit","--storage-opt"):
            self.assertIn(expected,args)

    def test_uncertain_create_is_bound_for_cleanup_and_never_retried(self):
        fake=FakeDocker(self.a,uncertain=True); producer=self.make(fake)
        with self.assertRaises(subprocess.TimeoutExpired):
            producer.container("prepare",self.a["builderImage"],"prepare.sh")
        self.assertEqual(producer.containers,[(fake.cid,self.a["builderImage"])])
        self.assertEqual(sum(call[:2]==("docker","create") for call in fake.calls),1)
        fake.uncertain=False
        producer.retire()
        self.assertTrue(fake.removed)

    def test_uncertain_foreign_container_is_refused(self):
        fake=FakeDocker(self.a,uncertain=True,foreign=True); producer=self.make(fake)
        with self.assertRaisesRegex(ValueError,"FOREIGN_UNCERTAIN_BUILD_CONTAINER"):
            producer.container("prepare",self.a["builderImage"],"prepare.sh")
        self.assertEqual(sum(call[:2]==("docker","create") for call in fake.calls),1)

    def test_cleanup_failure_is_not_hidden(self):
        fake=FakeDocker(self.a,cleanup_failure=True); fake.created=True
        producer=self.make(fake); producer.containers=[(fake.cid,self.a["builderImage"])]
        with self.assertRaisesRegex(ValueError,"EXACT_PRODUCER_CLEANUP_FAILED"):
            producer.retire()


    def test_verifier_executes_exact_hashed_bytes_despite_path_swap(self):
        import scripts.produce_official_sdk_pair as subject
        original=VERIFIER_PATH.read_bytes()
        copy=self.root/"official_sdk_release_admission.py"
        copy.write_bytes(original)
        reader=subject.read_plain_file
        def swap_after_read(path):
            raw=reader(path)
            copy.write_text("raise AssertionError('unverified replacement executed')")
            return raw
        with mock.patch.object(subject,"VERIFIER_PATH",copy), \
             mock.patch.object(subject,"read_plain_file",side_effect=swap_after_read) as read:
            module=load_bound_verifier(hashlib.sha256(original).hexdigest())
        self.assertEqual(module.SOURCE,fixtures.SOURCE)
        read.assert_called_once_with(copy)

    def test_input_ancestor_symlink_refused_before_manifest_or_ca_read(self):
        import scripts.produce_official_sdk_pair as subject
        for field in ("cacheManifest","caFile"):
            with self.subTest(field=field):
                directory=self.root/field
                directory.mkdir()
                target=directory/"input"
                target.write_bytes(b"data")
                original_lstat=os.lstat
                def changed(path,*args,**kwargs):
                    if Path(path)==directory:
                        return SimpleNamespace(st_mode=stat.S_IFLNK|0o777)
                    return original_lstat(path,*args,**kwargs)
                with mock.patch.object(subject.os,"lstat",side_effect=changed), \
                     mock.patch.object(subject.os,"open") as opened, \
                     self.assertRaisesRegex(ValueError,"PRODUCER_PATH_SYMLINK_REFUSED"):
                    read_plain_file(target)
                opened.assert_not_called()

    def test_special_input_refused_without_blocking_open(self):
        import scripts.produce_official_sdk_pair as subject
        target=self.root/"pipe"
        original_lstat=os.lstat
        def special(path,*args,**kwargs):
            if Path(path)==target:
                return SimpleNamespace(st_mode=stat.S_IFIFO|0o600)
            return original_lstat(path,*args,**kwargs)
        with mock.patch.object(subject.os,"lstat",side_effect=special), \
             mock.patch.object(subject.os,"open") as opened, \
             self.assertRaisesRegex(ValueError,"PRODUCER_INPUT_NOT_REGULAR"):
            read_plain_file(target)
        opened.assert_not_called()

    def test_delayed_create_observed_and_removed_without_recreate(self):
        fake=FakeDocker(self.a,uncertain=True); fake.missing_reads=2
        producer=self.make(fake)
        with self.assertRaises(subprocess.TimeoutExpired):
            producer.container("prepare",self.a["builderImage"],"prepare.sh")
        self.assertEqual(len(producer.pending_names),1)
        producer.retire()
        self.assertTrue(fake.removed)
        self.assertEqual(producer.pending_names,{})
        self.assertEqual(sum(call[:2]==("docker","create") for call in fake.calls),1)
        with self.assertRaisesRegex(ValueError,"PRODUCER_CREATE_ALREADY_RESERVED"):
            producer.container("prepare",self.a["builderImage"],"prepare.sh")

    def test_permanently_absent_uncertain_create_retains_reservation(self):
        fake=FakeDocker(self.a,uncertain=True); fake.never_appears=True
        producer=self.make(fake)
        with self.assertRaises(subprocess.TimeoutExpired):
            producer.container("prepare",self.a["builderImage"],"prepare.sh")
        with self.assertRaisesRegex(ValueError,"PRODUCER_CREATE_OUTCOME_UNRESOLVED"):
            producer.retire()
        self.assertEqual(len(producer.pending_names),1)
        self.assertFalse(fake.removed)
        events=[json.loads(line) for line in (producer.root/"events.jsonl").read_text().splitlines()]
        self.assertFalse(events[-1]["cleanupVerified"])
        self.assertFalse(events[-1]["reexecutionAllowed"])
        self.assertEqual(sum(call[:2]==("docker","create") for call in fake.calls),1)

    def test_remove_success_requires_actual_absence_readback(self):
        fake=FakeDocker(self.a); fake.created=True; fake.lie_remove=True
        producer=self.make(fake); producer.containers=[(fake.cid,self.a["builderImage"])]
        with self.assertRaisesRegex(ValueError,"PRODUCER_REMOVAL_NOT_VERIFIED"):
            producer.retire()
        self.assertEqual(producer.containers,[(fake.cid,self.a["builderImage"])])
        events=[json.loads(line) for line in (producer.root/"events.jsonl").read_text().splitlines()]
        self.assertNotIn("container-removed",[event["operation"] for event in events])

    def test_daemon_error_cannot_prove_container_absence(self):
        def broken(*args,**kwargs):
            return SimpleNamespace(returncode=1,stdout=b"",stderr=b"Cannot connect to the Docker daemon")
        producer=self.make(broken)
        with self.assertRaisesRegex(ValueError,"DOCKER_ABSENCE_NOT_PROVEN"):
            producer.container("prepare",self.a["builderImage"],"prepare.sh")


    def workspace_check(self, *, fstype="tmpfs", options="rw,nosuid,nodev", blocks=1024,
                        available=1024, mount=None):
        parent=self.root
        # Synthetic Linux mountinfo; no real mount or host operation.
        target=str(parent) if mount is None else mount
        line=f"99 1 0:99 / {target} {options} - {fstype} none rw,size=4096k\n"
        with mock.patch("scripts.produce_official_sdk_pair.sys.platform","linux"), \
             mock.patch("scripts.produce_official_sdk_pair.read_plain_file",return_value=line.encode()), \
             mock.patch("scripts.produce_official_sdk_pair.os.statvfs",create=True,
                        return_value=SimpleNamespace(f_blocks=blocks,f_bavail=available,f_frsize=4096)):
            return verify_bounded_workspace(parent,maximum_bytes=4*1024**2,minimum_free_bytes=4096)

    def test_workspace_requires_kernel_bounded_mount(self):
        result=self.workspace_check()
        self.assertEqual(result["capacityBytes"],4*1024**2)
        self.assertEqual(result["filesystem"],"tmpfs")

    def test_overlay_storage_option_cannot_substitute_for_bounded_bind(self):
        with self.assertRaisesRegex(ValueError,"BOUNDED_WORKSPACE_FILESYSTEM_REQUIRED"):
            self.workspace_check(fstype="ext4")

    def test_workspace_refuses_unbounded_capacity(self):
        with self.assertRaisesRegex(ValueError,"WORKSPACE_CAPACITY_NOT_ADMITTED"):
            self.workspace_check(blocks=1025)

    def test_workspace_refuses_insufficient_capacity(self):
        with self.assertRaisesRegex(ValueError,"WORKSPACE_CAPACITY_NOT_ADMITTED"):
            self.workspace_check(available=0)

    def test_workspace_requires_exact_mount_not_parent_filesystem(self):
        with self.assertRaisesRegex(ValueError,"DEDICATED_WORKSPACE_MOUNT_REQUIRED"):
            self.workspace_check(mount="/")

    def test_workspace_refuses_missing_nodev_nosuid(self):
        with self.assertRaisesRegex(ValueError,"BOUNDED_WORKSPACE_FILESYSTEM_REQUIRED"):
            self.workspace_check(options="rw")
