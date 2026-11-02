"""Inspect a portable serving reference. Never starts a process or contacts a cluster."""
import argparse,json
from pathlib import Path
IDS={'deepinfer-dspark-nccl-current','deepinfer-dspark-deepep-proposed','sglang-dspark-rollback'}
def plan(profile_id,model_path,review_proposed=False):
    if profile_id not in IDS:raise ValueError('Unknown profile')
    if not model_path.startswith('/') or any(c in model_path for c in '\r\n\x00'):raise ValueError('An absolute POSIX model path is required')
    p=json.loads((Path(__file__).parent/(profile_id+'.json')).read_text(encoding='utf8'))
    if p['status']=='PROPOSED-NOT-EXECUTED' and not review_proposed:raise ValueError('Proposed profile: use --review-proposed for inspection only; this does not authorize execution')
    if p['active_cap_total']!=8 or p['physical_gpus']!=4:raise ValueError('Reference capacity changed; review required')
    names=json.loads((Path(__file__).parent.parent/'naming.json').read_text(encoding='utf8'))
    sub=lambda s:s.replace('${MODEL_PATH}',model_path)
    engine_names=names['engines'][p['engine']]
    return {'profile':profile_id,'status':p['status'],'canonical_target_names':{'service':engine_names['service'],'deployment':engine_names['deployment'],'served_model_id':names['served_model_id'],'migration_status':names['status']},'argv':[sub(x) for x in p['command']+p['args']],'environment':{k:sub(v) for k,v in p['environment'].items()},'execution_authorized':False,'scope':'Launch-plan inspection only; mounted source, compiled libraries, overlays, weights, storage, authentication and network policy require independent review.'}
if __name__=='__main__':
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('profile',choices=sorted(IDS));a.add_argument('--model-path',required=True);a.add_argument('--review-proposed',action='store_true');v=a.parse_args();print(json.dumps(plan(v.profile,v.model_path,v.review_proposed),indent=2))
