import copy,importlib.util,json,re,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('feature_trace',ROOT/'scripts/build_feature_control_traceability.py');g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)
F=json.loads((ROOT/'docs/security-data/features.json').read_text(encoding='utf-8'));D=json.loads((ROOT/'docs/security-data/feature-reference-evidence.public.json').read_text(encoding='utf-8'))
class TraceabilityTests(unittest.TestCase):
 def test_all_original_rows_are_valid(self):self.assertTrue(g.validate(F,D))
 def test_all80_stable_feature_anchors_are_retained(self):
  page=g.render(F,D);self.assertEqual(sorted(map(int,re.findall(r'id="feature-(\d+)"',page))),list(range(1,81)))
 def test_missing_feature_mapping_is_rejected(self):
  d=copy.deepcopy(D);d['rows'].pop()
  with self.assertRaises(ValueError):g.validate(F,d)
 def test_duplicate_feature_mapping_is_rejected(self):
  d=copy.deepcopy(D);d['rows'][-1]=copy.deepcopy(d['rows'][0])
  with self.assertRaises(ValueError):g.validate(F,d)
 def test_unknown_evidence_reference_is_rejected(self):
  d=copy.deepcopy(D);d['rows'][0]['evidence_ids']=['missing']
  with self.assertRaises(ValueError):g.validate(F,d)
 def test_private_tool_row_identity_is_not_public_feature_evidence(self):
  d=copy.deepcopy(D);d['rows'][0]['private_tool_row_identity']=0
  with self.assertRaises(ValueError):g.validate(F,d)
 def test_incomplete_live_pass_is_refused(self):
  d=copy.deepcopy(D);d['evidence_groups'].append({'id':'invented','stage':'live-verified','result':'PASS'})
  with self.assertRaises(ValueError):g.validate(F,d)
 def test_generated_saved_page_is_exact_and_deterministic(self):
  a=g.render(F,D);self.assertEqual(a,g.render(F,D));self.assertEqual(a.encode(),(ROOT/'docs/FEATURE_CONTROL_TRACEABILITY.html').read_bytes())
if __name__=='__main__':unittest.main()
