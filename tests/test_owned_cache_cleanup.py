import ast,asyncio,json,textwrap,types,unittest
from pathlib import Path
SOURCE=(Path(__file__).resolve().parents[1]/'scripts/context_forwarder.py').read_text(encoding='utf-8')

class CleanupCancellationTests(unittest.IsolatedAsyncioTestCase):
 async def test_two_stops_drain_one_close_and_release_once(self):
  events=[];started=asyncio.Event();gate=asyncio.Event()
  async def close(sid):
   events.append(('close-start',sid));started.set();await gate.wait();events.append(('close-done',sid))
  async def abort(rid):events.append(('abort',rid))
  nodes=[next(n for n in ast.walk(ast.parse(SOURCE))if isinstance(n,ast.AsyncFunctionDef)and n.name==name)for name in ['perform_cleanup','cleanup']]
  header=chr(10).join(['async def exercise():',' cleaned=False',' ordinary_owned=False',' upstream=client=None',' cache_session_id="owned"',' rid="ours"',' lease={}',' cleanup_task=None'])+chr(10)
  body=textwrap.indent(chr(10).join(ast.unparse(n)for n in nodes),' ')+chr(10)
  tail=chr(10).join([' first=asyncio.create_task(cleanup())',' await started.wait()',' first.cancel()',' await asyncio.sleep(0)',' second=asyncio.create_task(cleanup())',' await asyncio.sleep(0)',' second.cancel()',' await asyncio.sleep(0)',' assert not first.done() and not second.done()',' assert not any(x[0]=="release"for x in events)',' gate.set()',' results=await asyncio.gather(first,second,return_exceptions=True)',' assert all(isinstance(x,asyncio.CancelledError)for x in results)',' await cleanup()',' return events'])
  env={'asyncio':asyncio,'close_owned_cache_reference':close,'abort':abort,'started':started,'gate':gate,'events':events,'timing':types.SimpleNamespace(finish=lambda:None),'interactive':types.SimpleNamespace(leave=lambda:None),'guard':types.SimpleNamespace(release=lambda v:events.append(('release',None)))};exec(header+body+tail,env);got=await env['exercise']();self.assertEqual(got,[('abort','ours'),('close-start','owned'),('close-done','owned'),('release',None)])
 async def test_open_confirms_identity_and_sets_backend_ttl(self):
  calls=[]
  class Client:
   async def __aenter__(self):return self
   async def __aexit__(self,*a):pass
   async def post(self,url,json):
    calls.append((url,json));return types.SimpleNamespace(raise_for_status=lambda:None,json=lambda:json['session_id'])
  n=next(n for n in ast.walk(ast.parse(SOURCE))if isinstance(n,ast.AsyncFunctionDef)and n.name=='open_owned_cache_reference');env={'httpx':types.SimpleNamespace(AsyncClient=lambda **k:Client()),'BACKEND':'http://backend.example','CONTEXT':1048576};exec(compile(ast.fix_missing_locations(ast.Module(body=[n],type_ignores=[])),'actual-open-helper','exec'),env);await env['open_owned_cache_reference']('owned');self.assertEqual(calls,[('http://backend.example/open_session',{'session_id':'owned','capacity_of_str_len':1048576,'streaming':False,'timeout':3900})])

if __name__=='__main__':unittest.main(verbosity=2)
