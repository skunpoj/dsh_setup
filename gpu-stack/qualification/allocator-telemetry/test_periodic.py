import unittest,importlib.util,json,os,ast
from pathlib import Path
from unittest.mock import patch,Mock
HERE=Path(__file__).parent
spec=importlib.util.spec_from_file_location('observer',HERE/'allocator_observer.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Event:
 def __init__(self,cycles=1):self.calls=[];self.cycles=cycles;self.stopped=False
 def wait(self,seconds):self.calls.append(seconds);self.cycles-=1;return self.stopped or self.cycles<0
 def set(self):self.stopped=True
class CUDA:
 def __init__(self,error=False):self.calls=[];self.error=error
 def memory_stats(self,device):
  self.calls.append(('memory_stats',device))
  if self.error:raise ValueError('sensitive exception text')
  return {k:i for i,k in enumerate(m.KEYS)}
class Worker:
 def __init__(self,**kw):self.kw=kw;self.started=0
 def start(self):self.started+=1
class TestPeriodic(unittest.TestCase):
 def setUp(self):m._periodic.clear();m._state.clear()
 def test_default_off_no_cuda_or_thread(self):
  with patch.dict(os.environ,{},clear=True):
   m._start_periodic(object(),lambda x:None,0,'native',.9,{},event_factory=lambda:self.fail('event'))
   m._start_from_foreground(object(),lambda x:None,0,'native',.9)
  self.assertEqual(m._periodic,{})
 def test_no_start_before_foreground_initialization(self):
  cuda=Mock();cuda.is_initialized.return_value=False
  with patch.dict(os.environ,{'DSH_QUALIFICATION_NATIVE_ALLOCATOR':'1','DSH_QUALIFICATION_PERIODIC_READONLY_COUNTERS':'1'}),patch.object(m,'_start_from_foreground')as start:
   m.observe(cuda,lambda x:None)
   start.assert_not_called();cuda.memory_stats.assert_not_called()
 def test_once_per_rank_daemon(self):
  made=[]
  def factory(**kw):w=Worker(**kw);made.append(w);return w
  with patch.dict(os.environ,{'DSH_QUALIFICATION_PERIODIC_READONLY_COUNTERS':'1'}):
   for rank in range(4):
    for _ in range(2):m._start_periodic(CUDA(),lambda x:None,rank,'native',.9,{'pid':rank+1,'startTicks':100},event_factory=Event,thread_factory=factory)
  self.assertEqual(len(made),4)
  self.assertTrue(all(w.kw['daemon']and w.started==1 for w in made))
  self.assertEqual([w.kw['args'][2]for w in made],[0,1,2,3])
 def test_only_read_stats_cadence_identity(self):
  for rank in range(4):
   cuda=CUDA();event=Event(2);logs=[];identity={'pid':rank+10,'startTicks':55}
   m._periodic_worker(cuda,logs.append,rank,'native',.922,identity,event,clock=lambda:5,wall=lambda:99)
   self.assertEqual(cuda.calls,[('memory_stats',rank)]*2);self.assertEqual(event.calls,[5,5,5])
   rows=[json.loads(x.split(' ',1)[1])for x in logs]
   self.assertTrue(all(r['processIdentity']==identity and r['sampleStartedUTC']==99 and r['sampleUTC']==99 and r['sampleKind']=='periodic-readonly'and set(r['counters'])==set(m.KEYS)for r in rows))
 def test_start_timestamp_precedes_actual_stat_read(self):
  order=[];cuda=CUDA();original=cuda.memory_stats
  def read(device):order.append('read');return original(device)
  cuda.memory_stats=read
  def wall():order.append('wall');return len(order)
  logs=[];m._periodic_worker(cuda,logs.append,0,'native',.9,{},Event(1),clock=lambda:5,wall=wall)
  self.assertEqual(order,['wall','read','wall'])
  row=json.loads(logs[0].split(' ',1)[1]);self.assertEqual(row['sampleStartedUTC'],1);self.assertEqual(row['sampleUTC'],3)
 def test_api_and_log_errors_stop_without_zero_or_retry(self):
  cuda=CUDA(True);event=Event(8);logs=[]
  m._periodic_worker(cuda,logs.append,0,'native',.9,{},event)
  self.assertEqual(len(cuda.calls),1);self.assertTrue(event.stopped)
  self.assertEqual(logs,['DSH_ALLOCATOR_OBSERVER_ERROR {"errorClass": "ValueError"}'])
  event=Event(8);cuda=CUDA()
  def badlog(x):raise RuntimeError('private data')
  m._periodic_worker(cuda,badlog,0,'native',.9,{},event)
  self.assertTrue(event.stopped);self.assertEqual(len(cuda.calls),1)
 def test_thread_failure_tombstone_no_retry(self):
  logs=[];factory=Mock(side_effect=RuntimeError('secret'))
  with patch.dict(os.environ,{'DSH_QUALIFICATION_PERIODIC_READONLY_COUNTERS':'1'}):
   for _ in range(2):m._start_periodic(CUDA(),logs.append,0,'native',.9,{},event_factory=Event,thread_factory=factory)
  self.assertEqual(factory.call_count,1);self.assertEqual(m._periodic[0]['state'],'failed');self.assertEqual(len(logs),1)
 def test_foreground_original_exact_except_optin_call(self):
  original=(HERE/'allocator_observer.original.py').read_text();new=(HERE/'allocator_observer.py').read_text()
  prefix=new.split('# Opt-in read-only telemetry.',1)[0]
  self.assertEqual(prefix.replace('    _start_from_foreground(cuda, emit, device, backend, fraction)\n','').rstrip(),original.rstrip())
  tree=ast.parse(new);worker=next(n for n in tree.body if isinstance(n,ast.FunctionDef)and n.name=='_periodic_worker')
  cuda_calls=[n.func.attr for n in ast.walk(worker)if isinstance(n,ast.Call)and isinstance(n.func,ast.Attribute)and isinstance(n.func.value,ast.Name)and n.func.value.id=='cuda']
  self.assertEqual(cuda_calls,['memory_stats'])
if __name__=='__main__':unittest.main()
