import copy,hashlib,importlib.util,json,re,subprocess,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('review',ROOT/'scripts/build_feature_owasp_review.py');g=importlib.util.module_from_spec(s);s.loader.exec_module(g)
F=json.loads((ROOT/'docs/security-data/features.json').read_text(encoding='utf-8'));R=json.loads((ROOT/'docs/security-data/feature-owasp-review.public.json').read_text(encoding='utf-8'))
class ReviewTests(unittest.TestCase):
 def test_all80_original_features_have_unique_review_rationales(self):
  self.assertTrue(g.validate(F,R));self.assertEqual(len({r['mapping_rationale'] for r in R['rows']}),80)
 def test_saved_review_has80_unique_rows_and_exactly10_domain_sections(self):
  page=g.render(F,R);self.assertEqual(sorted(map(int,re.findall(r'id="feature-(\d+)"',page))),list(range(1,81)));self.assertEqual(len(re.findall(r'<h2 id="asi\d\d">',page)),10);self.assertEqual(page.encode(),(ROOT/'docs/FEATURE_OWASP_REVIEW.html').read_bytes())
 def test_four_shared_evidence_rows_cover10domains_and_all_three_controls(self):
  rows=[r for r in R['rows'] if r['primary_category']=='ALL'];self.assertEqual([r['feature_id'] for r in rows],[63,64,65,66]);self.assertTrue(all(len(r['applicable_categories'])==10 and set(r['three_risk_controls'])=={'1','2','3'} for r in rows))
 def test_original_tags_and_operational_evidence_are_preserved(self):
  self.assertEqual(hashlib.sha256((ROOT/'docs/security-data/features.json').read_bytes()).hexdigest(),R['feature_source_sha256']);self.assertTrue(all(r['operational_evidence_unchanged'] is True for r in R['rows']));self.assertTrue(all('owner acceptance pending' in r['review_state'] for r in R['rows']))
 def test_missing_or_duplicate_row_is_refused(self):
  for change in ['missing','duplicate']:
   r=copy.deepcopy(R)
   if change=='missing':r['rows'].pop()
   else:r['rows'][-1]=copy.deepcopy(r['rows'][0])
   with self.assertRaises(ValueError):g.validate(F,r)
 def test_silent_category_or_risk_retagging_is_refused(self):
  for key,value in [('primary_category','ASI99'),('three_risk_controls',['1']),('applicable_categories',['ASI99'])]:
   r=copy.deepcopy(R);r['rows'][0][key]=value
   with self.assertRaises(ValueError):g.validate(F,r)
 def test_private_payload_or_public_workbook_url_is_refused(self):
  for key,value in [('public_page','private.xlsx'),('payload_included',True)]:
   r=copy.deepcopy(R);r['references'][1][key]=value
   with self.assertRaises(ValueError):g.validate(F,r)
  r=copy.deepcopy(R);r['rows'][0]['private_payload']='not-public'
  with self.assertRaises(ValueError):g.validate(F,r)
 def test_runtime_promotion_and_duplicate_rationale_are_refused(self):
  for key,value in [('operational_evidence_unchanged',False),('mapping_rationale',R['rows'][1]['mapping_rationale']),('review_state','live-verified')]:
   r=copy.deepcopy(R);r['rows'][0][key]=value
   with self.assertRaises(ValueError):g.validate(F,r)
 def test_both_refs_and_three_controls_visible_without_private_filename(self):
  page=g.render(F,R)
  for ref in R['references']:self.assertIn(ref['sha256'],page)
  for text in R['risk_controls'].values():self.assertIn(text,page)
  self.assertIn('(private; metadata only)',page);self.assertNotIn('tools_'+'register.json',page);self.assertNotIn('.xlsx',page)
 def test_cli_check_runs_on_saved_public_only_inputs(self):
  run=subprocess.run([sys.executable,str(ROOT/'scripts/build_feature_owasp_review.py'),'--check'],capture_output=True,text=True);self.assertEqual(run.returncode,0,run.stderr)
if __name__=='__main__':unittest.main()
