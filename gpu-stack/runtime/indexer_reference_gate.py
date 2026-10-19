"""Private candidate gate. Never run beside the live model."""
import sys
if sys.flags.optimize or not __debug__:
    raise RuntimeError('Qualification helpers require unoptimized Python')
import ast,json,gc,torch
from pathlib import Path

def method(name):
 tree=ast.parse(Path(name).read_text());f=next(x for x in ast.walk(tree)if isinstance(x,ast.FunctionDef)and x.name=='scores');m=ast.Module(body=[f],type_ignores=[]);ast.fix_missing_locations(m);ns={'torch':torch};exec(compile(m,name,'exec'),ns);return ns['scores']
a=method('original.py');b=method('patched.py')
assert torch.cuda.device_count()==4, 'Requires the four exclusive test GPUs'
rows=[];torch.manual_seed(42018)
for gpu in range(4):
 torch.cuda.set_device(gpu)
 free,total=torch.cuda.mem_get_info();assert free>8*(1<<30),'Refuse GPU math while the model or another owner occupies memory'
 for dtype in [torch.bfloat16,torch.float16,torch.float32]:
  for wd in [dtype,torch.float32]:
   for shape in [(1,1,1,32),(7,8,257,64),(64,8,513,32)]:
    m,h,n,d=shape;q=torch.randn(m,h,d,device='cuda',dtype=dtype);k=torch.randn(n,d,device='cuda',dtype=dtype);w=torch.randn(m,h,device='cuda',dtype=wd);before=[x.clone() for x in [q,k,w]]
    with torch.inference_mode():x=a(None,q,k,w);y=b(None,q,k,w)
    assert torch.isfinite(x).all() and torch.isfinite(y).all()
    torch.testing.assert_close(x,y,rtol=0,atol=0,equal_nan=True)
    assert all(torch.equal(u,v) for u,v in zip(before,[q,k,w]))
    rows.append({'gpu':gpu,'dtype':str(dtype),'weightsDtype':str(wd),'shape':shape,'bitwiseEqual':True,'inputsUnchanged':True})
    del q,k,w,before,x,y
 gc.collect();torch.cuda.empty_cache()
 # Both observed-prefix and larger-prefix score shapes allocate 1GiB scores.
 for m,n in [(256,131072),(64,524288)]:
  q=torch.randn(m,16,128,device='cuda',dtype=torch.bfloat16);k=torch.randn(n,128,device='cuda',dtype=torch.bfloat16);w=torch.randn(m,16,device='cuda',dtype=torch.bfloat16)
  peaks=[];reference=None
  for name,f in [('reference',a),('prototype',b)]:
   gc.collect();torch.cuda.empty_cache();torch.cuda.synchronize();base=torch.cuda.memory_allocated();torch.cuda.reset_peak_memory_stats()
   with torch.inference_mode():out=f(None,q,k,w)
   torch.cuda.synchronize();peak=torch.cuda.max_memory_allocated()-base
   if reference is None:reference=out.cpu()
   else:torch.testing.assert_close(out.cpu(),reference,rtol=0,atol=0,equal_nan=True)
   peaks.append({'variant':name,'peakAboveInputBytes':peak});del out
  assert peaks[1]['peakAboveInputBytes'] < peaks[0]['peakAboveInputBytes']-((1<<30)*3//2),'Expected removal of two full-score intermediates'
  rows.append({'gpu':gpu,'largeShape':[m,16,n,128],'bitwiseEqual':True,'memory':peaks})
  del q,k,w,reference;gc.collect();torch.cuda.empty_cache()
# Validate actual row tiling independently of the score-storage rewrite.
tiled=[]
for gpu in range(4):
 torch.cuda.set_device(gpu)
 for m,n in [(128,65536),(64,524288)]:
  q=torch.randn(m,16,128,device='cuda',dtype=torch.bfloat16);k=torch.randn(n,128,device='cuda',dtype=torch.bfloat16);w=torch.randn(m,16,device='cuda',dtype=torch.bfloat16)
  before=[v.clone()for v in [q,k,w]]
  with torch.inference_mode():
   torch.cuda.synchronize();reference_base=torch.cuda.memory_allocated();torch.cuda.reset_peak_memory_stats()
   expected=a(None,q,k,w).cpu();torch.cuda.synchronize();reference_peak=torch.cuda.max_memory_allocated()-reference_base
   tile_base=torch.cuda.memory_allocated();torch.cuda.reset_peak_memory_stats()
   chunk=max(1,(1<<28)//(16*n*2))
   parts=[b(None,q[i:i+chunk],k,w[i:i+chunk]).cpu()for i in range(0,m,chunk)]
   actual=torch.cat(parts);torch.cuda.synchronize();tile_peak=torch.cuda.max_memory_allocated()-tile_base
  torch.testing.assert_close(actual,expected,rtol=0,atol=0)
  assert all(torch.equal(x,y)for x,y in zip(before,[q,k,w]))
  assert tile_peak<reference_peak,'Tiled temporary memory must improve on the reference'
  tiled.append({'referencePeakAboveInputBytes':reference_peak,'tiledPeakAboveInputBytes':tile_peak,'gpu':gpu,'shape':[m,16,n,128],'rowTile':chunk,'scoreBudgetMiB':256,'bitwiseEqual':True,'inputsUnchanged':True})
  del q,k,w,before,expected,actual,parts;gc.collect();torch.cuda.empty_cache()
print(json.dumps({'scope':'Exclusive-GPU mathematical equivalence and temporary allocation gate only; not DSH acceptance','passed':True,'cases':rows,'tiledCases':tiled}))
