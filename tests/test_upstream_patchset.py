import importlib.util,hashlib,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('exporter',Path(__file__).resolve().parents[1]/'scripts/export_upstream_patchset.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class PatchsetTests(unittest.TestCase):
 def run_fixture(self,original=b'original\n',changed=b'patched\n',path='example/lib/index.js'):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);before=root/'before';after=root/'after'
   for base,data in [(before,original),(after,changed)]:
    p=base/'node_modules/@deepseek-ai'/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
   c={'baselineVersion':'1.0.0','targets':[{'path':path,'sha256':hashlib.sha256(b'original\n').hexdigest()}]}
   result=m.export(c,before,after,root/'out');patch=(root/'out/compatibility.patch').read_text();return result,patch
 def test_reviewable_diff_and_both_hashes(self):
  r,p=self.run_fixture();self.assertIn('-original',p);self.assertIn('+patched',p);self.assertEqual(len(r['targets']),1)
 def test_stale_upstream_refused(self):
  with self.assertRaisesRegex(ValueError,'Unreviewed'):self.run_fixture(original=b'changed upstream\n')
 def test_silently_skipped_mutation_refused(self):
  with self.assertRaisesRegex(ValueError,'skipped'):self.run_fixture(changed=b'original\n')
 def test_protected_target_retained_and_mutation_refused(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);before=root/'before';after=root/'after';relative=Path('node_modules/@deepseek-ai/example/lib/index.js')
   for base in [before,after]:
    p=base/relative;p.parent.mkdir(parents=True);p.write_bytes(b'original\n')
   c={'baselineVersion':'1.0.0','targets':[{'path':'example/lib/index.js','sha256':hashlib.sha256(b'original\n').hexdigest(),'patched':False}]}
   result=m.export(c,before,after,root/'out');self.assertFalse(result['targets'][0]['patched']);self.assertEqual((root/'out/compatibility.patch').read_bytes(),b'')
   (after/relative).write_bytes(b'permission bypass\n')
   with self.assertRaisesRegex(ValueError,'Protected'):m.export(c,before,after,root/'bad')
if __name__=='__main__':unittest.main()
