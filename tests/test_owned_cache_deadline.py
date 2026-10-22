import ast,asyncio,time,unittest
from pathlib import Path
new={'context_forwarder.py':(Path(__file__).resolve().parents[1]/'scripts/context_forwarder.py').read_text(encoding='utf-8')}
def fn(name,env):
    node=next(n for n in ast.parse(new['context_forwarder.py']).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))and n.name==name)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'actual-candidate-'+name,'exec'),env)
    return env[name]

class DeadlineTests(unittest.IsolatedAsyncioTestCase):
    def env(self):
        env={'time':time,'asyncio':asyncio};fn('cache_reference_remaining',env);fn('within_cache_deadline',env);return env
    async def test_expired_owner_never_starts_dispatch(self):
        env=self.env();calls=[]
        def factory():calls.append(True);raise AssertionError('Must not start')
        with self.assertRaises(TimeoutError):await env['within_cache_deadline'](factory,time.monotonic()-1)
        self.assertEqual(calls,[])
    async def test_timeout_drains_cancelled_operation(self):
        env=self.env();events=[]
        async def operation():
            try:await asyncio.sleep(1)
            finally:await asyncio.sleep(.01);events.append('drained')
        with self.assertRaises(TimeoutError):await env['within_cache_deadline'](operation,time.monotonic()+.01)
        self.assertEqual(events,['drained'])
    async def test_ordinary_calls_unchanged(self):
        env=self.env()
        async def operation():return 'ordinary'
        self.assertEqual(await env['within_cache_deadline'](operation,None),'ordinary')
    async def test_same_deadline_applies_to_warm_send_and_stream(self):
        f=new['context_forwarder.py'];self.assertEqual(f.count('cache_reference_deadline = time.monotonic()+3300'),1)
        self.assertIn("within_cache_deadline(lambda: guard.warm",f)
        self.assertIn("within_cache_deadline(lambda: client.send",f)
        self.assertIn('owned_remaining = cache_reference_remaining(cache_reference_deadline)',f)
        self.assertIn("'timeout':3900",f)

if __name__=='__main__':unittest.main(verbosity=2)
