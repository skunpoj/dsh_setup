import importlib.util,pathlib,sys,types,unittest,asyncio
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
class FakeChat:
 def __init__(self,**kw): self.received=kw;self.model_name=kw['model'];self.openai_api_base=kw['base_url'];self.http_client=kw['http_client'];self.http_async_client=kw['http_async_client']
class FakeClient:
 def __init__(self,**kw): self.trust_env=kw.get('trust_env');self.options=kw
 def close(self):pass
 async def aclose(self):pass
if 'langchain_openai' not in sys.modules:
 f=types.ModuleType('langchain_openai');f.ChatOpenAI=FakeChat;sys.modules['langchain_openai']=f
try:import httpx
except ImportError:
 f=types.ModuleType('httpx');f.Client=FakeClient;f.AsyncClient=FakeClient;sys.modules['httpx']=f
spec=importlib.util.spec_from_file_location('managed_source',ROOT/'container/dsh_agent_model.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
ds=importlib.util.spec_from_file_location('cli_source',ROOT/'container/dsh-cli-managed.py');dc=importlib.util.module_from_spec(ds);ds.loader.exec_module(dc)
sp=importlib.util.spec_from_file_location('launcher_source',ROOT/'container/deepagents-managed.py');l=importlib.util.module_from_spec(sp);sp.loader.exec_module(l)
P={'model':m.MODEL,'base_url':'http://litellm.dsh.svc.cluster.local:4000/v1'}
class PolicyTests(unittest.TestCase):
 def test_policy(self):self.assertEqual(m.validate_policy(P),P)
 def test_models(self):
  for x in ['other','deepseek-flash','',None]:
   with self.subTest(x=x),self.assertRaises(ValueError):m.validate_policy(dict(P,model=x))
 def test_endpoints(self):
  for x in ['https://api.openai.com/v1','http://litellm.dsh.svc.cluster.local.evil:4000/v1','http://litellm.dsh.svc.cluster.local:4000/v1?x=1',''.join(['http://', 'u', ':', 'p', '@', 'litellm.dsh.svc.cluster.local:4000/v1']),'file:///tmp/key']:
   with self.subTest(x=x),self.assertRaises(ValueError):m.validate_policy(dict(P,base_url=x))
 def test_model_override(self):
  with self.assertRaises(ValueError):m.checked_options({'model':'other'},P)
 def test_endpoint_override(self):
  with self.assertRaises(ValueError):m.checked_options({'base_url':'https://example.com'},P)
 def test_key_override(self):
  with self.assertRaises(ValueError):m.checked_options({'api_key':'SYNTHETIC'},P)
 def test_hidden_routing(self):
  for k in ['model_kwargs','extra_body','openai_proxy','http_client','default_headers','api_base']:
   with self.subTest(k=k),self.assertRaises(ValueError):m.checked_options({k:{}},P)
 def test_bounds(self):
  for x in [{'max_tokens':8193},{'max_tokens':True},{'timeout':3601},{'max_retries':3},{'temperature':-1}]:
   with self.subTest(x=x),self.assertRaises(ValueError):m.checked_options(x,P)
 def test_harmless_options(self):self.assertEqual(m.checked_options({'max_tokens':12,'temperature':0},P),{'max_tokens':12,'temperature':0})
 def test_cli_rejects_configuration(self):
  for a in [['auth'],['--model','other'],['--model-params','{}'],['--install','x'],['--yolo'],['--base-url','https://example.com']]:
   with self.subTest(a=a),self.assertRaises(ValueError):l.arguments(a)
 def test_cli_task(self):self.assertEqual(l.arguments(['-n','read README']),['-n','read README'])
 def test_cli_bound(self):
  with self.assertRaises(ValueError):l.arguments(['-n','x'*65537])
 def test_sanitized_environment(self):
  e=l.environment({'ANTHROPIC_API_KEY':'SYNTHETIC','OPENAI_API_KEY':'SYNTHETIC','OPENAI_BASE_URL':'https://example.com','HTTP_PROXY':'http://example.com','PYTHONPATH':'/tmp','LANGSMITH_TRACING':'true','PATH':'/tmp','HOME':'/tmp','LANG':'C.UTF-8'})
  for key in ['ANTHROPIC_API_KEY','OPENAI_API_KEY','OPENAI_BASE_URL','HTTP_PROXY','PYTHONPATH']:self.assertNotIn(key,e)
  self.assertEqual(e['LANGSMITH_TRACING'],'false');self.assertEqual(e['PATH'],'/usr/local/bin:/usr/bin:/bin')
 def test_constructor_fixed_model_and_proxy_disabled(self):
  with patch.object(m,'load_policy',return_value=P),patch.object(m,'TOKEN',types.SimpleNamespace(read_text=lambda:'SYNTHETIC_TEST_KEY')):
   obj=m.DSHManagedChat();self.assertEqual(obj.model_name,m.MODEL);self.assertEqual(obj.openai_api_base,P['base_url']);self.assertFalse(getattr(obj.http_client,'_trust_env',getattr(obj.http_client,'trust_env',None)));self.assertFalse(getattr(obj.http_async_client,'_trust_env',getattr(obj.http_async_client,'trust_env',None)));obj.http_client.close();asyncio.run(obj.http_async_client.aclose())
 def test_dsh_cli_aliases(self):
  self.assertEqual(dc.invocation('dsh-cli',[]),('tui',[]));self.assertEqual(dc.invocation('dsh-run',['read README']),('headless',['read README']));self.assertEqual(dc.invocation('dsh-sdk',[]),('sdk',[]))
 def test_dsh_cli_rejects_overrides(self):
  for a in [['--patch','x'],['--model','other'],['plugin'],['--profile','web']]:
   with self.subTest(a=a),self.assertRaises(ValueError):dc.invocation('dsh-cli',a)
 def test_syntax(self):
  for p in (ROOT/'container').glob('*.py'):compile(p.read_text(),str(p),'exec')
if __name__=='__main__':unittest.main()
