import hashlib,importlib.util,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];HELPER=ROOT/'runtime/indexer_dequant_patch.py'
if not HELPER.exists():HELPER=ROOT/'scripts/indexer_dequant_patch.py'
spec=importlib.util.spec_from_file_location('dequant_patch',HELPER);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class DequantPatchTests(unittest.TestCase):
 def test_qualified_source_and_output_pins(self):
  self.assertEqual(module.SOURCE_SHA256,'cb118c1cd0ba11a7ea216242e485d6098162984e6e21df3b40b5248b320af190')
  self.assertEqual(module.OUTPUT_SHA256,'61d6b6b4e535e849b772b4e71e3823e7d5186eda9a3a66613b993f6b36da25d8')
 def test_source_drift_refused(self):
  with self.assertRaises(ValueError):module.patch(module.ANCHOR)
 def test_only_reviewed_anchor_changes(self):
  fixture='class Pool:\n    def get_index_k_dequant(self,slots):\n'+module.ANCHOR+'\n# preserve unrelated source\n'
  with patch.object(module,'SOURCE_SHA256',hashlib.sha256(fixture.encode()).hexdigest()):
   self.assertEqual(module.patch(fixture).replace(module.REPLACEMENT,module.ANCHOR),fixture)
 def test_ambiguous_anchor_refused(self):
  fixture=module.ANCHOR*2
  with patch.object(module,'SOURCE_SHA256',hashlib.sha256(fixture.encode()).hexdigest()):
   with self.assertRaises(ValueError):module.patch(fixture)
 def test_existing_output_is_preserved(self):
  with tempfile.TemporaryDirectory(prefix='dsh-pool-fence-')as d:
   assert Path(d).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
   src=Path(d)/'input.py';dst=Path(d)/'output.py';src.write_text('unqualified\n');dst.write_text('preserve\n')
   p=subprocess.run([sys.executable,str(HELPER),str(src),str(dst)],capture_output=True)
   self.assertNotEqual(p.returncode,0);self.assertEqual(dst.read_text(),'preserve\n');self.assertEqual(src.read_text(),'unqualified\n')
 def test_bad_source_does_not_create_output(self):
  with tempfile.TemporaryDirectory(prefix='dsh-pool-fence-')as d:
   assert Path(d).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
   src=Path(d)/'input.py';dst=Path(d)/'output.py';src.write_text('unqualified\n')
   p=subprocess.run([sys.executable,str(HELPER),str(src),str(dst)],capture_output=True)
   self.assertNotEqual(p.returncode,0);self.assertFalse(dst.exists());self.assertEqual(src.read_text(),'unqualified\n')
if __name__=='__main__':unittest.main()
