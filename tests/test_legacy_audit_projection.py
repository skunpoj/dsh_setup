import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('audit',Path(__file__).parents[1]/'scripts/collect_legacy_audit.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


class AuditProjectionTests(unittest.TestCase):
    def test_schema_scope_and_malformed_records(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'events.jsonl'
            good={'time':'2026-10-17T00:00:00Z','event':'terminal.open','user':'user2','environment':'internet','password':'must-not-export','body':'private'}
            p.write_text(json.dumps(good)+'\ninvalid\n'+json.dumps({**good,'event':'private-body'})+'\n')
            rows=audit.project(folder,'legacy-dsh2')
            self.assertEqual(len(rows),1)
            self.assertEqual(set(rows[0]),{'time','event','user','environment'})
            self.assertEqual(rows[0]['environment'],'legacy-dsh2/internet')
            self.assertNotIn('must-not-export',json.dumps(rows))
            try: (Path(folder)/'events.1.jsonl').symlink_to(p)
            except OSError: return  # Windows may not grant symlink creation; Linux fixture covers this branch.
            self.assertEqual(len(audit.project(folder,'legacy-dsh2')),1)


if __name__=='__main__':unittest.main()
