import subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'runtime'
if not SOURCE.exists():SOURCE=ROOT/'scripts'
class QualificationModeTests(unittest.TestCase):
 def test_optimized_interpreters_refused_before_optional_imports(self):
  names=['indexer_scratch_patch.py','indexer_tile_patch.py','indexer_dequant_patch.py','indexer_reference_gate.py','indexer_dequant_reference_gate.py']
  for name in names:
   for mode in ['-O','-OO']:
    with self.subTest(helper=name,mode=mode):
     p=subprocess.run([sys.executable,mode,str(SOURCE/name)],capture_output=True,text=True)
     self.assertNotEqual(p.returncode,0)
     self.assertIn('Qualification helpers require unoptimized Python',p.stderr)
     self.assertNotIn('No module named',p.stderr)
if __name__=='__main__':unittest.main()
