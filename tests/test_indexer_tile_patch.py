import hashlib,importlib.util,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
HELPER=ROOT/'runtime/indexer_tile_patch.py'
if not HELPER.exists():HELPER=ROOT/'scripts/indexer_tile_patch.py'
spec=importlib.util.spec_from_file_location('tile_patch',HELPER);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class TilePatchTests(unittest.TestCase):
 def test_image_source_pin_and_budget(self):
  self.assertEqual(module.EXPECTED,'486900ed693af0573a941d6b6656ebc01ccb7ff1c44584e43ad3c0fb00a3c3a9')
  self.assertEqual(module.REPLACEMENT,'_TORCH_INDEXER_SCORE_BUDGET_BYTES = 1 << 27')
 def test_drift_is_refused(self):
  with self.assertRaises(ValueError):module.patch(module.ANCHOR+'\n')
 def test_only_the_exact_budget_changes(self):
  fixture=module.ANCHOR+'\n# unrelated control\nCONTEXT=1048576\n'
  with patch.object(module,'EXPECTED',hashlib.sha256(fixture.encode()).hexdigest()):
   self.assertEqual(module.patch(fixture).replace(module.REPLACEMENT,module.ANCHOR),fixture)
 def test_duplicate_anchor_is_refused(self):
  fixture=(module.ANCHOR+'\n')*2
  with patch.object(module,'EXPECTED',hashlib.sha256(fixture.encode()).hexdigest()):
   with self.assertRaises(ValueError):module.patch(fixture)
 def test_cli_keeps_existing_output(self):
  with tempfile.TemporaryDirectory(prefix='dsh-tile-')as d:
   assert Path(d).resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
   src=Path(d)/'in.py';dst=Path(d)/'out.py';src.write_text('unqualified\n');dst.write_text('preserve\n')
   p=subprocess.run([sys.executable,str(HELPER),str(src),str(dst)],capture_output=True)
   self.assertNotEqual(p.returncode,0);self.assertEqual(dst.read_text(),'preserve\n');self.assertEqual(src.read_text(),'unqualified\n')
if __name__=='__main__':unittest.main()
