"""Metadata-only regression fixtures; these are not live acceptance evidence."""
import copy,unittest
from test_feature_control_traceability import F,D,g
class LiveClaimTests(unittest.TestCase):
 def fixture(self,feature=7):
  d=copy.deepcopy(D)
  group={'id':'synthetic-live-schema-fixture','stage':'live-verified','result':'PASS','test_ids':['synthetic-schema-only'],'date_utc':'2026-11-11T04:00:00Z','source_commit':'a'*40,'image_digest':'sha256:'+'b'*64,'environment':'Synthetic metadata fixture, no actual deployment','owner':'fixture-owner','evidence_link':'synthetic-schema-receipt.json','positive_behavior_verified':True,'negative_behavior_verified':True,'feature_ids':[7],'scope':'Synthetic schema coverage only, not runtime evidence'}
  d['evidence_groups'].append(group);row=next(x for x in d['rows'] if x['feature_id']==feature);row.update(live_acceptance_state='live-verified',deployment_state='deployed',acceptance_owner='fixture-owner',evidence_ids=[group['id']]);return d,row,group
 def test_source_only_group_cannot_promote_a_live_row(self):
  d=copy.deepcopy(D);r=next(x for x in d['rows'] if x['feature_id']==7);r.update(live_acceptance_state='live-verified',deployment_state='deployed',acceptance_owner='fixture-owner')
  with self.assertRaises(ValueError):g.validate(F,d)
 def test_unknown_live_state_is_rejected(self):
  d=copy.deepcopy(D);d['rows'][0]['live_acceptance_state']='operational PASS'
  with self.assertRaises(ValueError):g.validate(F,d)
 def test_live_group_cannot_accept_a_different_feature(self):
  d,_,_=self.fixture(feature=8)
  with self.assertRaises(ValueError):g.validate(F,d)
 def test_mutable_image_tag_is_not_an_application_digest(self):
  d,_,group=self.fixture();group['image_digest']='runtime:latest'
  with self.assertRaises(ValueError):g.validate(F,d)
 def test_behavior_result_strings_are_not_true_booleans(self):
  d,_,group=self.fixture();group['positive_behavior_verified']='false'
  with self.assertRaises(ValueError):g.validate(F,d)
 def test_live_row_needs_an_acceptance_owner(self):
  d,row,_=self.fixture();row['acceptance_owner']=None
  with self.assertRaises(ValueError):g.validate(F,d)
 def test_live_row_needs_a_deployed_state(self):
  d,row,_=self.fixture();row['deployment_state']='unverified'
  with self.assertRaises(ValueError):g.validate(F,d)
 def test_live_timestamp_must_be_utc(self):
  d,_,group=self.fixture();group['date_utc']='2026-11-11T11:00:00+07:00'
  with self.assertRaises(ValueError):g.validate(F,d)
 def test_complete_synthetic_metadata_fixture_is_structurally_valid(self):
  d,_,_=self.fixture();self.assertTrue(g.validate(F,d))
 def test_rendered_live_metadata_does_not_claim_zero_rows(self):
  d,_,_=self.fixture();page=g.render(F,d)
  self.assertNotIn('No row currently has established live acceptance.',page)
  self.assertIn('Recorded live-acceptance metadata: 1 row(s).',page)
if __name__=='__main__':unittest.main()
