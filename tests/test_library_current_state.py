import copy,importlib.util,json,re,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('current_state',ROOT/'scripts/build_library_current_state.py');current=importlib.util.module_from_spec(spec);spec.loader.exec_module(current)
def load(path):return json.loads((ROOT/'docs'/path).read_text(encoding='utf-8'))
class CurrentLibraryStateTests(unittest.TestCase):
 def setUp(self):
  self.state=load('LIBRARY_CURRENT_STATE.public.json');self.formats=load('LIBRARY_FORMATS.public.json');self.features=load('security-data/features.json');self.evidence=load('security-data/feature-reference-evidence.public.json')
 def test_current_map_preserves_all80_ids_and10domains(self):
  page,md=current.render(self.state,self.formats,self.features,self.evidence)
  self.assertEqual({int(n) for n in re.findall(r'#feature-(\d+)',page)},set(range(1,81)))
  self.assertEqual(len(re.findall(r'<h3>ASI\d\d ',page)),10)
  self.assertIn('under active qualification',page);self.assertIn('Four cross-cutting evidence rows',page)
  self.assertIn('\n\n',md);self.assertIn('Internal tool-and-risk assessment workbook',page)
 def test_private_workbook_cannot_be_marked_public(self):
  self.state['reference_sources'][1]['public_payload']=True
  with self.assertRaises(ValueError):current.validate(self.state,self.formats,self.features,self.evidence)
  self.state['reference_sources'][1]['public_payload']=False;self.state['reference_sources'][1]['filename']='Unreviewed private filename'
  with self.assertRaises(ValueError):current.validate(self.state,self.formats,self.features,self.evidence)
 def test_acceptance_count_cannot_promote_unverified_features(self):
  self.state['feature_ledger_established_live_acceptances']=80
  with self.assertRaises(ValueError):current.validate(self.state,self.formats,self.features,self.evidence)
 def test_format_inventory_totals_and_all_registered_paths(self):
  self.assertTrue(current.validate(self.state,self.formats,self.features,self.evidence));page=current.index_panels(self.state,self.formats)
  self.assertEqual(len(self.formats['records']),11)
  for record in self.formats['records']:self.assertIn(record['path'],page)
  broken=copy.deepcopy(self.formats);broken['records'][0]['units']+=1
  with self.assertRaises(ValueError):current.validate(self.state,broken,self.features,self.evidence)
 def test_affected_login_deck_is_legacy_and_points_to_canonical_controls(self):
  record=next(r for r in self.formats['records'] if r['path']=='presentations/APP_LOGIN_MAIN_TEST_EN.pptx')
  self.assertIn('RETAINED LEGACY / NOT CURRENT',record['edition_alignment'])
  self.assertIn('former DQ reference',record['edition_alignment'])
  self.assertEqual(record['sha256'],'ac948ca909c4934a4b08b9865a1b530a65628a1ae3eba8be2f5a90d7879190ee')
  self.assertEqual(set(record['current_guidance_urls']),{'THREE_RISK_CONTROLS.html','DSH_CURRENT_GUIDE.html#reference-controls','ARCHITECTURE_AND_ISOLATION_AT_A_GLANCE.html'})
  self.assertEqual(self.state['powerpoint_revision_summary']['content_and_local_render_verified'],2)
  self.assertEqual(self.state['powerpoint_revision_summary']['retained_legacy_decks'],1)
  page,md=current.render(self.state,self.formats,self.features,self.evidence)
  self.assertIn('RETAINED LEGACY / NOT CURRENT',page)
  self.assertIn('href="DSH_CURRENT_GUIDE.html#reference-controls"',page)
  self.assertIn('retained legacy/not current',md)

if __name__=='__main__':unittest.main()
