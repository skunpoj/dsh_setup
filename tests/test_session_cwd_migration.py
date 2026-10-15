import importlib.util,json,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('cwd',Path(__file__).resolve().parents[1]/'scripts/session_cwd_migration.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Codec:
 def header(self,p):
  raw=p.read_bytes().split(b'\n',1)[0]+b'\n';return json.loads(raw),len(raw)
 def encode(self,h):return (json.dumps(h)+'\n').encode()
class MigrationTests(unittest.TestCase):
 def test_changes_only_header_preserves_events_and_original(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);root=r/'sessions';p=root/'old'/'id'/'v4.jsonl.zstd';p.parent.mkdir(parents=True);target=r/'workspace';target.mkdir();h={'id':'id','cwd':'/root/Spark','version':4};events=b'{"user":"do not replace /root/Spark in conversation"}\n';original=Codec().encode(h)+events;p.write_bytes(original)
   result=m.migrate(root,{'/root/Spark':str(target)},r/'recovery',Codec());dest=root/m.project_key(str(target))/'id'/p.name
   self.assertEqual(result['sessionRecordsCorrected'],1);self.assertEqual(dest.read_bytes().split(b'\n',1)[1],events);self.assertEqual((r/'recovery/old/id'/p.name).read_bytes(),original);self.assertFalse(p.exists())
 def test_unmapped_root_refuses_before_changes(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);p=r/'sessions/x/id/v4.jsonl.zstd';p.parent.mkdir(parents=True);p.write_bytes(Codec().encode({'id':'id','cwd':'/root/unapproved'}));before=p.read_bytes()
   with self.assertRaises(ValueError):m.migrate(r/'sessions',{},r/'recovery',Codec())
   self.assertEqual(p.read_bytes(),before);self.assertFalse((r/'recovery').exists())
 def test_destination_collision_refuses_before_changes(self):
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);root=r/'sessions';target=r/'workspace';target.mkdir();p=root/'old/id/v4.jsonl.zstd';p.parent.mkdir(parents=True);p.write_bytes(Codec().encode({'id':'id','cwd':'/root'}));dest=root/m.project_key(str(target))/'id'/p.name;dest.parent.mkdir(parents=True);dest.write_bytes(Codec().encode({'id':'id','cwd':str(target)}))
   with self.assertRaises(ValueError):m.migrate(root,{'/root':str(target)},r/'recovery',Codec())
   self.assertFalse((r/'recovery').exists())
if __name__=='__main__':unittest.main()
