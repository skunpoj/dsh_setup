"""Exclusive-GPU FP4 equivalence/peak gate; --cpu never initializes CUDA."""
import sys
if sys.flags.optimize or not __debug__:
    raise RuntimeError('Qualification helpers require unoptimized Python')
import ast,torch,json,argparse,typing,gc,types,sys
from pathlib import Path
ap=argparse.ArgumentParser();ap.add_argument('--cpu',action='store_true');args=ap.parse_args();torch.set_num_threads(1)
if args.cpu:
 assert not torch.cuda.is_initialized()
 table=torch.tensor([0.,.5,1.,1.5,2.,3.,4.,6.,-0.,-.5,-1.,-1.5,-2.,-3.,-4.,-6.],dtype=torch.float32)
 for name in ['sglang','sglang.srt','sglang.srt.layers','sglang.srt.layers.quantization','sglang.srt.layers.quantization.fp8']:
  module=types.ModuleType(name);module.__path__=[];sys.modules[name]=module
 sys.modules['sglang.srt.layers.quantization.fp8'].DSV4_DEQUANT_FP4_TABLE=table
 devices=['cpu']
else:
 assert torch.cuda.device_count()==4,'Only run before the model on the exclusive four GPUs'
 devices=['cuda:'+str(i)for i in range(4)]
def method(name):
 t=ast.parse(Path(name).read_text());f=next(x for x in ast.walk(t)if isinstance(x,ast.FunctionDef)and x.name=='get_index_k_dequant');m=ast.Module(body=[f],type_ignores=[]);ast.fix_missing_locations(m);ns={'torch':torch,'Optional':typing.Optional};exec(compile(m,name,'exec'),ns);return ns['get_index_k_dequant']
reference=method('dequant_original.py');candidate=method('dequant_patched.py')
class Pool:
 def __init__(self,size,page,device,dtype=torch.uint8,exhaustive=False):
  self.size=size;self.page_size=page;self.start_layer=5;self.use_fp4_indexer=True;pages=max(1,(size+page-1)//page);buf=torch.randint(0,256,(pages,page*68),dtype=torch.uint8,device=device)
  if exhaustive:
   assert size==4096
   ids=torch.arange(size,device=device);r=(ids//page).unsqueeze(1);off=ids%page;cols=(off*64).unsqueeze(1)+torch.arange(64,device=device);code=(ids%16).to(torch.uint8);buf[r,cols]=(code|(code<<4)).unsqueeze(1);sc=(page*64+off*4).unsqueeze(1)+torch.arange(4,device=device);buf[r,sc]=(ids//16).to(torch.uint8).unsqueeze(1)
  self.index_k_with_scale_buffer=[buf.view(dtype)]
cases=[];memory=[];torch.manual_seed(42019)
for device in devices:
 if device!='cpu':
  torch.cuda.set_device(device);assert torch.cuda.mem_get_info()[0]>8*(1<<30),'Refuse concurrent GPU model occupancy'
 for page in [1,16,128]:
  for dtype in [torch.uint8,torch.int8]:
   pool=Pool(257,page,device,dtype);before=pool.index_k_with_scale_buffer[0].clone()
   slots_cases=[None,torch.empty(0,device=device,dtype=torch.int64),torch.tensor([0,1,1,256],device=device,dtype=torch.int64),torch.tensor([256,2,0,2],device=device,dtype=torch.int32),torch.tensor([-1,-page],device=device,dtype=torch.int64)]
   for slots in slots_cases:
    saved=slots.clone()if slots is not None else None
    with torch.inference_mode():a=reference(pool,5,slots);b=candidate(pool,5,slots)
    assert a.shape==b.shape and a.dtype==b.dtype==torch.bfloat16
    assert torch.equal(a.view(torch.int16),b.view(torch.int16)),'FP4 output bits changed'
    assert torch.equal(pool.index_k_with_scale_buffer[0],before),'Compressed input modified'
    if slots is not None:assert torch.equal(slots,saved),'Slot indices modified'
    cases.append({'device':device,'page':page,'bufferDtype':str(dtype),'slotCase':'none'if slots is None else str(slots.dtype)+':'+str(slots.numel()),'bitwiseEqual':True,'inputsUnchanged':True})
   del pool,before,a,b,slots_cases
  pool=Pool(4096,page,device,exhaustive=True);before=pool.index_k_with_scale_buffer[0].clone()
  with torch.inference_mode():a=reference(pool,5);b=candidate(pool,5)
  assert torch.equal(a.view(torch.int16),b.view(torch.int16))and torch.equal(pool.index_k_with_scale_buffer[0],before)
  cases.append({'device':device,'page':page,'all16CodesAnd256Exponents':True,'bitwiseEqual':True,'inputsUnchanged':True});del pool,before,a,b
 if device!='cpu':
  for size in [397312,524288]:
   gc.collect();torch.cuda.empty_cache();pool=Pool(size,128,device);slots=torch.arange(size,device=device);before=pool.index_k_with_scale_buffer[0].clone();peaks=[];expected=None
   for name,f in [('reference',reference),('candidate',candidate)]:
    gc.collect();torch.cuda.empty_cache();torch.cuda.synchronize();baseline=torch.cuda.memory_allocated();torch.cuda.reset_peak_memory_stats()
    with torch.inference_mode():out=f(pool,5,slots)
    torch.cuda.synchronize();peaks.append({'variant':name,'peakAboveInputsBytes':torch.cuda.max_memory_allocated()-baseline})
    if expected is None:expected=out.cpu().view(torch.int16)
    else:assert torch.equal(expected,out.cpu().view(torch.int16))
    del out
   assert peaks[1]['peakAboveInputsBytes']<peaks[0]['peakAboveInputsBytes']-128*(1<<20),'Need a measured temporary-memory reduction'
   assert torch.equal(before,pool.index_k_with_scale_buffer[0]);memory.append({'device':device,'slots':size,'bitwiseEqual':True,'inputsUnchanged':True,'peaks':peaks});del pool,slots,before,expected;gc.collect();torch.cuda.empty_cache()
if args.cpu:assert not torch.cuda.is_initialized()
print(json.dumps({'scope':'Exclusive-Dequant reference gate'if not args.cpu else'CPU dequant reference only','passed':True,'cases':cases,'memory':memory,'cudaInitialized':torch.cuda.is_initialized()}))
