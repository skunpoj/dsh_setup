import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import upstream_source_diff as diff


def archive(entries):
    out=io.BytesIO()
    with tarfile.open(fileobj=out,mode='w:gz') as tf:
        for name,value,kind in entries:
            member=tarfile.TarInfo(name);member.type=kind
            member.size=len(value) if kind==tarfile.REGTYPE else 0
            tf.addfile(member,io.BytesIO(value) if member.size else None)
    blob=out.getvalue()
    return blob,'sha512-'+base64.b64encode(hashlib.sha512(blob).digest()).decode()


class SourceDiffTests(unittest.TestCase):
    def test_archive_integrity_and_data(self):
        blob,integrity=archive([('package/lib/x.js',b'payload',tarfile.REGTYPE)])
        self.assertEqual(diff.archive_files(blob,integrity,{'lib/x.js'}),{'lib/x.js':b'payload'})
        with self.assertRaisesRegex(ValueError,'integrity mismatch'):
            diff.archive_files(blob+b'x',integrity,set())

    def test_unsafe_archive_members_refused(self):
        for name,kind in [('package/../escape',tarfile.REGTYPE),('/package/a',tarfile.REGTYPE),('package/a\\b',tarfile.REGTYPE),('package/link',tarfile.SYMTYPE),('package/hard',tarfile.LNKTYPE),('package/device',tarfile.CHRTYPE)]:
            with self.subTest(name=name,kind=kind):
                blob,integrity=archive([(name,b'',kind)])
                with self.assertRaises(ValueError): diff.archive_files(blob,integrity,set())

    def test_duplicates_and_limits(self):
        blob,integrity=archive([('package/a',b'x',tarfile.REGTYPE)]*2)
        with self.assertRaisesRegex(ValueError,'Duplicate'):diff.archive_files(blob,integrity,set())
        blob,integrity=archive([('package/a',b'xx',tarfile.REGTYPE)])
        with patch.object(diff,'MAX_FILE',1),self.assertRaisesRegex(ValueError,'size limit'):diff.archive_files(blob,integrity,set())
        with patch.object(diff,'MAX_MEMBERS',0),self.assertRaisesRegex(ValueError,'member limit'):diff.archive_files(blob,integrity,set())

    def test_url_allowlist(self):
        for url in ['http://registry.npmjs.org/@deepseek-ai/dsh','https://evil.example/@deepseek-ai/dsh','https://registry.npmjs.org.evil/@deepseek-ai/dsh','https://registry.npmjs.org/@other/x','https://registry.npmjs.org/@deepseek-ai/dsh?x=1']:
            with self.assertRaises(ValueError):diff.validate_url(url)
        with self.assertRaises(ValueError): diff.NoRedirect().redirect_request(None,None,302,'',{},'https://evil.example')

    def test_download_byte_bound(self):
        response=io.BytesIO(b'12345')
        with patch.object(diff.urllib.request,'build_opener') as opener:
            opener.return_value.open.return_value=response
            with self.assertRaisesRegex(ValueError,'size limit'):diff.fetch('https://registry.npmjs.org/@deepseek-ai/dsh',4)

    def test_download_deadline(self):
        with patch.object(diff.urllib.request,'build_opener') as opener,patch.object(diff.time,'monotonic',side_effect=[0,46]):
            opener.return_value.open.return_value=io.BytesIO(b'')
            with self.assertRaisesRegex(ValueError,'deadline'):diff.fetch('https://registry.npmjs.org/@deepseek-ai/dsh')

    def test_matrix_is_actionable_and_requires_reviewed_version(self):
        version='0.2.1-rc.2';name='@deepseek-ai/dsh-module'
        identity=json.dumps({'name':name,'version':version}).encode()
        blob,integrity=archive([('package/package.json',identity,tarfile.REGTYPE),('package/lib/ok.js',b'ok',tarfile.REGTYPE),('package/lib/change.js',b'new',tarfile.REGTYPE)])
        contract={'baselineVersion':version,'targets':[{'path':'dsh-module/lib/'+file+'.js','sha256':hashlib.sha256(b'ok').hexdigest()} for file in ['ok','change','missing']]}
        package={'version':version,'dependencies':{name:version},'dist':{'tarball':'https://registry.npmjs.org/@deepseek-ai/dsh/-/root.tgz'}}
        rootblob,rootintegrity=archive([('package/package.json',json.dumps({'name':'@deepseek-ai/dsh','version':version,'dependencies':{name:version}}).encode(),tarfile.REGTYPE)])
        package['dist']['integrity']=rootintegrity
        with patch.object(diff,'metadata',return_value={'name':name,'version':version,'dist':{'tarball':'https://registry.npmjs.org/@deepseek-ai/dsh-module/-/x.tgz','integrity':integrity}}),patch.object(diff,'fetch',side_effect=lambda url: rootblob if url.endswith('root.tgz') else blob):
            result=diff.inspect_candidate(package,contract)
            self.assertEqual([x['status'] for x in result['targets']],['compatible','changed','missing'])
            self.assertFalse(result['buildAllowed']);self.assertFalse(result['packageCodeExecuted'])
            contract['targets']=contract['targets'][:1]
            self.assertTrue(diff.inspect_candidate(package,contract)['buildAllowed'])
            contract['baselineVersion']='0.2.0-rc.2'
            self.assertFalse(diff.inspect_candidate(package,contract)['buildAllowed'])

    def test_missing_and_unresolved_dependencies_block(self):
        c={'baselineVersion':'1.0.0','targets':[{'path':'dsh-module/lib/x.js','sha256':'0'*64}]}
        for deps,status in [({},'missing-package'),({'@deepseek-ai/dsh-module':'^1.0.0'},'unresolved-version')]:
            package={'name':'@deepseek-ai/dsh','version':'1.0.0','dependencies':deps}
            blob,integrity=archive([('package/package.json',json.dumps(package).encode(),tarfile.REGTYPE)])
            package['dist']={'tarball':'https://registry.npmjs.org/@deepseek-ai/dsh/-/root.tgz','integrity':integrity}
            with patch.object(diff,'fetch',return_value=blob):
                r=diff.inspect_candidate(package,c)
            self.assertFalse(r['buildAllowed']);self.assertEqual(r['targets'][0]['status'],status)

    def test_transitive_exact_official_dependency_is_resolved(self):
        version='1.0.0'; module='@deepseek-ai/dsh-module'
        package={'name':'@deepseek-ai/dsh','version':version,'dependencies':{'@deepseek-ai/dsh-base':version}}
        rootblob,rootintegrity=archive([('package/package.json',json.dumps(package).encode(),tarfile.REGTYPE)])
        package['dist']={'tarball':'https://registry.npmjs.org/@deepseek-ai/dsh/-/root.tgz','integrity':rootintegrity}
        moduleblob,moduleintegrity=archive([('package/package.json',json.dumps({'name':module,'version':version}).encode(),tarfile.REGTYPE),('package/lib/x.js',b'x',tarfile.REGTYPE)])
        c={'baselineVersion':version,'targets':[{'path':'dsh-module/lib/x.js','packageVersion':version,'registryIntegrity':moduleintegrity,'sha256':hashlib.sha256(b'x').hexdigest()}]}
        def meta(name,v):
            if name=='@deepseek-ai/dsh-base': return {'dependencies':{module:version}}
            return {'dist':{'tarball':'https://registry.npmjs.org/@deepseek-ai/dsh-module/-/x.tgz','integrity':moduleintegrity}}
        with patch.object(diff,'metadata',side_effect=meta),patch.object(diff,'fetch',side_effect=lambda url:rootblob if url.endswith('root.tgz') else moduleblob):
            self.assertTrue(diff.inspect_candidate(package,c)['buildAllowed'])
            c['targets'][0]['packageVersion']='0.0.0'
            r=diff.inspect_candidate(package,c)
            self.assertFalse(r['buildAllowed']);self.assertEqual(r['targets'][0]['status'],'changed-package-contract')

    def test_target_package_can_also_hold_transitive_targets(self):
        version='1.0.0';base='@deepseek-ai/dsh-base';module='@deepseek-ai/dsh-module'
        package={'name':'@deepseek-ai/dsh','version':version,'dependencies':{base:version}}
        archives={};infos={}
        for name,deps,files in [('@deepseek-ai/dsh',{base:version},{}),(base,{module:version},{'base.yml':b'b'}),(module,{}, {'lib/x.js':b'x'})]:
            identity={'name':name,'version':version,'dependencies':deps}
            blob,integrity=archive([('package/package.json',json.dumps(identity).encode(),tarfile.REGTYPE)]+[('package/'+p,v,tarfile.REGTYPE) for p,v in files.items()])
            url='https://registry.npmjs.org/'+name+'/-/fixture.tgz'
            archives[url]=blob;infos[name]={**identity,'dist':{'tarball':url,'integrity':integrity}}
        c={'baselineVersion':version,'targets':[{'path':'dsh-base/base.yml','sha256':hashlib.sha256(b'b').hexdigest()},{'path':'dsh-module/lib/x.js','sha256':hashlib.sha256(b'x').hexdigest()}]}
        with patch.object(diff,'metadata',side_effect=lambda name,v:infos[name]),patch.object(diff,'fetch',side_effect=lambda url:archives[url]):
            self.assertTrue(diff.inspect_candidate(infos['@deepseek-ai/dsh'],c)['buildAllowed'])

    def test_workflow_copy_and_no_write_job(self):
        root=Path(__file__).resolve().parents[1]
        workflow=(root/'.github/workflows/upstream-candidate.yml').read_bytes()
        self.assertEqual(workflow,(root/'docs/UPSTREAM_CANDIDATE_WORKFLOW.yml').read_bytes())
        self.assertNotIn(b'contents: write',workflow)
        self.assertIn(b"if not d['buildAllowed']",workflow)
        self.assertIn(b'--source-diff candidate-evidence/source-diff.json',workflow)

if __name__=='__main__':unittest.main()
