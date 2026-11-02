import copy
import hashlib
import json
import stat
import time
from types import SimpleNamespace
from unittest.mock import Mock,patch
import unittest
from scripts import openshell_bootstrap as bootstrap
from scripts.openshell_broker_transport import NativeBrokerTransport
from scripts.openshell_task_binding import BrokerOpenShellService


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.now=time.time();self.path='/etc/dsh-native-admission/server.json'
        self.module='/opt/dsh/scripts/admitted_native.py';self.source=b'# pinned native factory\n'
        self.config={'kind':'DSH_OPENSHELL_SERVER_ADMISSION_V1','mode':'qualification','subject':'alice','generation':'g1',
            'expiresAt':self.now+300,'namespace':'dsh-openshell-test-20261028','sourceCommit':'a'*40,
            'imageLock':{r:'sha256:'+'b'*64 for r in bootstrap.ROLES},'policySha256':'c'*64,
            'transportModule':self.module,'transportSha256':hashlib.sha256(self.source).hexdigest(),'acceptance':None}
        self.files={self.module:self.source}
        self.registry=Mock();self.registry.tasks={}
        self.transport=NativeBrokerTransport(self.registry,Mock(),Mock(),lambda *_:None)
        self.factory=Mock(return_value=self.transport);self.loader=Mock(return_value=self.factory)
        self.server=SimpleNamespace()

    def reader(self,path):
        if path==self.path:return json.dumps(self.config).encode()
        return self.files[path]

    def configure(self):
        return bootstrap.configure(self.server,self.registry,self.path,clock=lambda:self.now,
            reader=self.reader,factory_loader=self.loader)

    def production(self):
        self.config.update(mode='production',namespace='dsh-openshell')
        gates=[]
        for i in range(1,26):
            path='/etc/dsh-native-admission/gates/T%02d.json'%i
            self.files[path]=json.dumps({'syntheticLoaderFixtureOnly':True,'gate':'T%02d'%i}).encode()
            gates.append({'id':'T%02d'%i,'result':'PASSED','evidence':{'path':path,'sha256':hashlib.sha256(self.files[path]).hexdigest()}})
        rb='/etc/dsh-native-admission/rollback.json';self.files[rb]=b'synthetic loader fixture only'
        receipt={'kind':'DSH_OPENSHELL_NATIVE25_ACCEPTANCE_V1','imageLock':self.config['imageLock'],
            'policySha256':self.config['policySha256'],'transportSha256':self.config['transportSha256'],
            'sourceCommit':self.config['sourceCommit'],'acceptedBy':'synthetic-unit-test-reviewer','gates':gates,
            'rollback':{'result':'PASSED','evidence':{'path':rb,'sha256':hashlib.sha256(self.files[rb]).hexdigest()}}}
        self.receipt_path='/etc/dsh-native-admission/accepted.json'
        self.set_receipt(receipt)
        return receipt

    def set_receipt(self,receipt):
        raw=json.dumps(receipt).encode();self.files[self.receipt_path]=raw
        self.config['acceptance']={'path':self.receipt_path,'sha256':hashlib.sha256(raw).hexdigest()}

    def test_no_descriptor_keeps_backend_disabled(self):
        self.assertFalse(bootstrap.configure(self.server,self.registry,None,factory_loader=self.loader))
        self.assertFalse(hasattr(self.server,'openshell_service'));self.loader.assert_not_called()

    def test_finite_qualification_loads_only_exact_typed_transport(self):
        self.assertTrue(self.configure())
        self.assertIs(self.server.openshell_service.transport,self.transport)
        self.assertEqual(self.server.openshell_service.subject,'alice')
        self.assertEqual(self.server.openshell_service.admission_expires_at,self.config['expiresAt'])
        self.factory.assert_called_once_with(registry=self.registry,admission=self.config)

    def test_expired_or_foreign_scope_never_loads_factory(self):
        for field,value in [('expiresAt',self.now-1),('namespace','llm'),('sourceCommit','0'*40),('transportModule','/workspace/user.py')]:
            original=self.config[field];self.config[field]=value
            with self.assertRaises(ValueError):self.configure()
            self.config[field]=original
        self.loader.assert_not_called()

    def test_wrong_source_hash_and_fallback_transport_refused(self):
        self.files[self.module]=b'changed'
        with self.assertRaisesRegex(ValueError,'NATIVE_TRANSPORT_HASH_MISMATCH'):self.configure()
        self.loader.assert_not_called();self.files[self.module]=self.source
        self.factory.return_value=object()
        with self.assertRaisesRegex(ValueError,'UNAPPROVED_NATIVE_TRANSPORT'):self.configure()
        self.assertFalse(hasattr(self.server,'openshell_service'))

    def test_production_requires_all_25_and_distinct_verified_evidence(self):
        receipt=self.production();receipt['gates'].pop();self.set_receipt(receipt)
        with self.assertRaisesRegex(ValueError,'NATIVE25_ACCEPTANCE_INCOMPLETE'):self.configure()
        self.loader.assert_not_called()
        receipt=self.production();self.files[receipt['gates'][0]['evidence']['path']]=b'changed'
        with self.assertRaisesRegex(ValueError,'NATIVE_EVIDENCE_HASH_MISMATCH'):self.configure()
        self.loader.assert_not_called()

    def test_production_rejects_duplicate_gate_and_failed_rollback(self):
        receipt=self.production();receipt['gates'][1]=copy.deepcopy(receipt['gates'][0]);self.set_receipt(receipt)
        with self.assertRaisesRegex(ValueError,'NATIVE25_ACCEPTANCE_INCOMPLETE'):self.configure()
        receipt=self.production();receipt['rollback']['result']='NOT_RUN';self.set_receipt(receipt)
        with self.assertRaisesRegex(ValueError,'NATIVE_ROLLBACK_INCOMPLETE'):self.configure()
        self.loader.assert_not_called()

    def test_complete_synthetic_receipt_checks_bytes_before_factory(self):
        self.production();self.assertTrue(self.configure())
        self.assertIsInstance(self.server.openshell_service,BrokerOpenShellService)

    def test_user_writable_admission_and_workspace_path_refused(self):
        with patch.object(bootstrap.os,'open',return_value=9),patch.object(bootstrap.os,'close') as close,\
             patch.object(bootstrap.os,'fstat',return_value=SimpleNamespace(st_mode=stat.S_IFREG|0o666,st_uid=0)):
            with self.assertRaisesRegex(ValueError,'UNPROTECTED_ADMISSION_FILE'):bootstrap.read_protected(self.path)
        close.assert_called_once_with(9)
        with self.assertRaisesRegex(ValueError,'UNPROTECTED_ADMISSION_PATH'):bootstrap.protected_path('/workspace/a')


if __name__=='__main__':unittest.main()
