import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('promotion',Path(__file__).resolve().parents[1]/'container/promote_packages.py')
promotion=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(promotion)


@unittest.skipUnless(hasattr(os,'O_NOFOLLOW'),'Linux operator tests; also executed in the promotion job')
class PackagePromotionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.incoming=self.root/'incoming';self.approved=self.root/'approved'
        self.incoming.mkdir();self.approved.mkdir();self.manifest=self.root/'manifest'
        self.good=b'audited dependency fixture\n';self.digest=hashlib.sha256(self.good).hexdigest()

    def tearDown(self):self.temp.cleanup()
    def run_promotion(self):return promotion.promote(self.manifest,self.incoming,self.approved)
    def row(self,path='python/test.whl',digest=None):
        self.manifest.write_text((digest or self.digest)+'  '+path+'\n')
    def seed(self):
        (self.incoming/'python').mkdir();(self.incoming/'python/test.whl').write_bytes(self.good);self.row()

    def test_verified_idempotent_and_no_overwrite(self):
        self.seed();self.assertEqual(self.run_promotion(),1);self.assertEqual(self.run_promotion(),1)
        target=self.approved/'python/test.whl';self.assertEqual(target.read_bytes(),self.good)
        target.chmod(0o644);target.write_bytes(b'conflict')
        with self.assertRaises(ValueError):self.run_promotion()
        self.assertEqual(target.read_bytes(),b'conflict')

    def test_source_and_destination_symlinks_denied(self):
        self.seed();outside=self.root/'outside';outside.mkdir();(outside/'test.whl').write_bytes(self.good)
        (self.incoming/'python/test.whl').unlink();(self.incoming/'python/test.whl').symlink_to(outside/'test.whl')
        with self.assertRaises(OSError):self.run_promotion()
        (self.incoming/'python/test.whl').unlink();(self.incoming/'python').rmdir();(self.incoming/'python').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(OSError):self.run_promotion()
        (self.incoming/'python').unlink();(self.incoming/'python').mkdir();(self.incoming/'python/test.whl').write_bytes(self.good)
        (self.approved/'python').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(OSError):self.run_promotion()
        self.assertEqual((outside/'test.whl').read_bytes(),self.good)

    def test_hash_failure_publishes_no_other_rows(self):
        self.seed();(self.incoming/'python/bad.whl').write_bytes(b'tampered')
        self.manifest.write_text(self.manifest.read_text()+self.digest+'  python/bad.whl\n')
        with self.assertRaises(ValueError):self.run_promotion()
        self.assertFalse((self.approved/'python/test.whl').exists())

    def test_path_replacement_after_open_cannot_change_promoted_bytes(self):
        self.seed();actual_open=os.open;swapped=False
        def swap(path,*args,**kwargs):
            nonlocal swapped
            fd=actual_open(path,*args,**kwargs)
            if path=='test.whl' and not swapped:
                swapped=True;(self.incoming/'python/test.whl').rename(self.incoming/'python/old.whl')
                (self.incoming/'python/test.whl').write_bytes(b'substituted after source opened')
            return fd
        with patch.object(promotion.os,'open',side_effect=swap):
            # Mocking os.open changes its identity; retain the platform capability check.
            with patch.object(promotion.os,'supports_dir_fd',os.supports_dir_fd|{promotion.os.open}):self.run_promotion()
        self.assertTrue(swapped);self.assertEqual((self.approved/'python/test.whl').read_bytes(),self.good)

    def test_traversal_and_empty_approval_refused(self):
        self.manifest.write_text('# no approval\n')
        with self.assertRaises(ValueError):self.run_promotion()
        self.row('../escape')
        with self.assertRaises(ValueError):self.run_promotion()


if __name__=='__main__':unittest.main()
