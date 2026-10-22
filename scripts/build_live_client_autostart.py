"""Build the source-pinned native DSH startup package; no network or model calls."""
import argparse
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def build(bundle,root=ROOT):
 files={'reactivate.py':(root/'container/reactivate-live-clients.py').read_text(encoding='utf-8'),'install_live_client_layer.py':(root/'scripts/install_live_client_layer.py').read_text(encoding='utf-8'),'bundle.json':json.dumps(bundle,separators=(',',':'))}
 files['boot.json']=json.dumps({'bundle_sha256':hashlib.sha256(files['bundle.json'].encode()).hexdigest()})
 pins={n:hashlib.sha256(v.encode()).hexdigest()for n,v in files.items()}
 files['startup.mjs']=(root/'container/live-client-autostart.mjs').read_text(encoding='utf-8').replace('PINS',json.dumps(pins))
 identity=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()[:16]
 return {'identity':identity,'files':files}
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('bundle',type=Path);parser.add_argument('output',type=Path);args=parser.parse_args();args.output.write_text(json.dumps(build(json.loads(args.bundle.read_text(encoding='utf-8'))),indent=2),encoding='utf-8')
