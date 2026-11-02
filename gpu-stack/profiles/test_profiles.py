import unittest,json
from pathlib import Path
from inspect_profile import plan
class Profiles(unittest.TestCase):
 def test_engine_routes_use_distinct_canonical_services(self):
  a=plan('deepinfer-dspark-nccl-current','/models/approved')['canonical_target_names'];b=plan('sglang-dspark-rollback','/models/approved')['canonical_target_names'];self.assertEqual(a['service'],'deepinfer-dspark');self.assertEqual(b['service'],'sglang-dspark');self.assertNotEqual(a['service'],b['service']);self.assertEqual(a['deployment'],'deepinfer-dspark');self.assertEqual(b['deployment'],'sglang-dspark');self.assertIn('verified',a['migration_status'])
 def test_current_entrypoint_and_transport(self):
  p=plan('deepinfer-dspark-nccl-current','/models/approved');self.assertIn('serve/openai_server.py',p['argv']);self.assertEqual(p['environment']['DEEPINFER_EP_COMM_BACKEND'],'nccl');self.assertFalse(p['execution_authorized']);self.assertNotIn('${MODEL_PATH}',str(p))
 def test_sglang_is_distinct(self):
  p=plan('sglang-dspark-rollback','/models/approved');self.assertEqual(p['argv'][:3],['python3','-m','sglang.launch_server']);self.assertIn('DSPARK',p['argv'])
 def test_proposed_refuses_normal_inspection(self):
  with self.assertRaises(ValueError):plan('deepinfer-dspark-deepep-proposed','/models/approved')
 def test_only_expert_transport_changes(self):
  root=Path(__file__).parent;a=json.loads((root/'deepinfer-dspark-nccl-current.json').read_text());b=json.loads((root/'deepinfer-dspark-deepep-proposed.json').read_text());self.assertEqual(a['args'],b['args']);self.assertEqual([k for k in a['environment'] if a['environment'][k]!=b['environment'][k]],['DEEPINFER_EP_COMM_BACKEND']);self.assertEqual(b['environment']['DEEPINFER_CP_COMM_BACKEND'],'nccl')
 def test_unqualified_remains_unauthorized(self):
  self.assertFalse(plan('deepinfer-dspark-deepep-proposed','/models/approved',True)['execution_authorized'])
 def test_bad_inputs(self):
  for name,path in [('../x','/m'),('deepinfer-dspark-nccl-current','relative'),('deepinfer-dspark-nccl-current','/m\nx')]:
   with self.assertRaises(ValueError):plan(name,path)
if __name__=='__main__':unittest.main()
