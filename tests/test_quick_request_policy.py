import json, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class QuickPolicyTest(unittest.TestCase):
    def test_preserves_instructions_and_history_and_refuses_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);agents=p/'AGENTS.md';agents.write_bytes(b'User-specific rules\n');sessions=p/'sessions';sessions.mkdir();history=sessions/'sample.bin';history.write_bytes(bytes(range(256)));backup=p/'before';policy=ROOT/'config/quick-request-policy.md'
            cmd=[sys.executable,str(ROOT/'scripts/install_quick_request_policy.py'),'--agents',str(agents),'--policy',str(policy),'--sessions',str(sessions),'--backup',str(backup)]
            r=subprocess.run(cmd,capture_output=True,text=True,check=True);result=json.loads(r.stdout)
            self.assertTrue(result['historiesUnchanged']);self.assertEqual(backup.read_bytes(),b'User-specific rules\n');self.assertTrue(agents.read_bytes().startswith(backup.read_bytes()));self.assertEqual(history.read_bytes(),bytes(range(256)))
            installed=agents.read_bytes();r=subprocess.run(cmd,capture_output=True,text=True);self.assertNotEqual(r.returncode,0);self.assertEqual(installed,agents.read_bytes())
            agents.write_bytes(backup.read_bytes());self.assertEqual(agents.read_bytes(),b'User-specific rules\n')
    def test_image_instruction_generation_preserves_user_rules(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);agents=p/'AGENTS.md';agents.write_text('Keep my private rules\n',encoding='utf-8')
            js="""const fs=require('fs');const dshHome=process.argv[1];const src=fs.readFileSync(process.argv[2],'utf8');const start=src.indexOf('  const quickPolicy = ');const end=src.indexOf('  console.log(\"[CONFIG] Populated AGENTS.md',start);if(start<0||end<0)throw Error('Managed block missing');const block=src.slice(start,end);const realExists=fs.existsSync;fs.existsSync=(p)=>p==='/workspace'?false:realExists(p);const agentsMdContent='Default guidelines';eval(block);eval(block);"""
            subprocess.run(['node','-e',js,str(p),str(ROOT/'scripts/configure_models.js')],check=True,capture_output=True)
            content=agents.read_text(encoding='utf-8');self.assertTrue(content.startswith('Keep my private rules\n'));self.assertEqual(content.count('<!-- DSH:BOUNDED-QUICK-REQUESTS:v1 -->'),1);self.assertIn((ROOT/'config/quick-request-policy.md').read_text(encoding='utf-8'),content)
if __name__=='__main__':unittest.main()
