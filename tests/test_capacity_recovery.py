"""Verify interruption recovery without rerunning tools against allocated data."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from capacity_controller import reconcile,read_json


@unittest.skipUnless(os.name=='posix','Linux descriptor and directory durability semantics')
class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'policy').mkdir();(self.root/'inventory').mkdir()
        self.write('policy/policy.json',{'version':1,'enabled':True,'warmSpareSlots':1})
        self.write('policy/assignments.json',{'observedAt':datetime.now(timezone.utc).isoformat(),'registeredAccounts':3,'assignedSlots':[]})
        self.routes={'secure':{'host':'private-secure'},'internet':{'host':'private-internet'}}
        self.write('inventory/inventory.json',{'slots':{'qualified':{'state':'ready','qualification':{'status':'passed'},'routes':self.routes}}})
        self.write('inventory/pool.json',{'slots':{}})
        class Worker:
            def resources(inner):return {k:1 for k in ['cpuAfterPair','memoryGiBAfterPair','podsAfterPair','storageGiBAfterPair']}
            def prepare_and_qualify(inner,*args):raise AssertionError('Must not re-read an allocated runtime')
        self.worker=Worker()
    def tearDown(self):self.temp.cleanup()
    def write(self,name,value):(self.root/name).write_text(json.dumps(value))
    def test_qualification_receipt_recovers_unpublished_route(self):
        self.assertEqual(reconcile(self.root,self.worker)['action'],'wait')
        self.assertEqual(read_json(self.root/'inventory/pool.json')['slots']['qualified'],self.routes)
        self.assertEqual(reconcile(self.root,self.worker)['action'],'wait')
    def test_existing_published_route_is_never_replaced(self):
        old={'slots':{'qualified':{'secure':{'host':'different'}}}};self.write('inventory/pool.json',old)
        with self.assertRaises(RuntimeError):reconcile(self.root,self.worker)
        self.assertEqual(read_json(self.root/'inventory/pool.json'),old)
    def test_symlink_mutable_input_and_fifo_are_refused(self):
        target=self.root/'policy/assignments.json';link=self.root/'policy/link';link.symlink_to(target)
        with self.assertRaises(OSError):read_json(link)
        fifo=self.root/'policy/fifo';os.mkfifo(fifo)
        with self.assertRaises(ValueError):read_json(fifo)

if __name__=='__main__':unittest.main()
