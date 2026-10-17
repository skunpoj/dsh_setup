"""Summarize one completed real DSH review and its overlapping short requests."""
import argparse,json,re,subprocess,statistics
from pathlib import Path
from datetime import datetime,timedelta,timezone
from repository_review_metrics import turn_stats
ap=argparse.ArgumentParser();ap.add_argument('--directory',type=Path,required=True);a=ap.parse_args();p=a.directory
r=json.loads((p/'long-result.json').read_text(encoding='utf-8'));c=json.loads((p/'controller.json').read_text(encoding='utf-8'))
assert r['status']=='completed'
baseline=r.get('baselineSessionStats')
if r.get('continuedSession') and not baseline:
 parent=json.loads((p.parent/'long-result.json').read_text(encoding='utf-8'))
 if parent['sessionId']!=r['sessionId'] or parent['status']!='completed':raise ValueError('No verified same-session baseline')
 parent_end=datetime.fromisoformat(parent['startUTC'])+timedelta(seconds=parent['elapsedSeconds'])
 if parent_end>=datetime.fromisoformat(r['startUTC']):raise ValueError('Baseline was not completed before this turn')
 baseline=parent['projection']['sessionStats']
current_stats=turn_stats(r,baseline)

start=datetime.fromisoformat(r['startUTC']);end=start+timedelta(seconds=r['elapsedSeconds'])
log=subprocess.run(['kubectl','-n','llm','logs','deploy/litellm','-c','context-forwarder','--since-time='+c['startUTC'],'--timestamps=true'],capture_output=True,text=True,timeout=45)
warms=[]
for line in log.stdout.splitlines():
 if 'dsh_final_wire_warmed' not in line:continue
 ts,body=line.split(' ',1)
 try:
  v=json.loads(body);t=datetime.fromisoformat(ts.replace('Z','+00:00'));v['completionUTC']=t.isoformat();v['startUTC']=(t-timedelta(seconds=v['seconds'])).isoformat();warms.append(v)
 except Exception:pass
matches=[v for v in warms if v['tokens']==r['lastUsage']['inputTokens']]
assert matches,'No matching final warming lifecycle'
w=matches[-1];admitted=datetime.fromisoformat(w['startUTC']);first=None
for e in r['events']:
 if e['type']=='assistant/message':
  for item in e['data'].get('stream',[]):
   if item.get('type')=='text-chunks':
    t=datetime.fromtimestamp(item['time0']/1000,timezone.utc);first=t if first is None else min(first,t)
shorts=[]
for pair in c['shortPairs']:
 for s in pair['results']:
  st=datetime.fromisoformat(s['startUTC']);en=st+timedelta(seconds=s['elapsedSeconds'])
  phase='before-admission' if en<=admitted else 'during-preparation-or-generation' if st>=admitted else 'crossed-admission'
  shorts.append({'startUTC':s['startUTC'],'seconds':s['elapsedSeconds'],'correct':s['expectedTextPresent'],'persisted':s['persistedPromptMatches'],'longRunningAfterPair':pair['longRunningAfter'],'phase':phase,'duringGeneration':bool(first and st>=first),'overlapWithinLong':en<=end})
live=[s for s in shorts if s['phase']=='during-preparation-or-generation' and s['longRunningAfterPair'] and s['overlapWithinLong']]
logs=subprocess.run(['kubectl','-n','llm','logs','deploy/vllm-deepseek-v4-1-flash','--since-time='+c['startUTC'],'--timestamps=true'],capture_output=True,text=True,timeout=45)
lines=[]
for line in logs.stdout.splitlines():
 try:t=datetime.fromisoformat(line.split(' ',1)[0].replace('Z','+00:00'))
 except ValueError:continue
 if admitted<=t<=end:lines.append(line)
text='\n'.join(lines);signatures=['CUDA out of memory','OutOfMemoryError','illegal memory access','Scheduler exception','memory mapping failed with OOM']
summary={'startUTC':r['startUTC'],'finishUTC':end.isoformat(),'actualClient':'DSH agent HTTP RPC on disposable current-image runtime; not Claude Code or TrueForge','usage':r['lastUsage'],'totalElapsedSeconds':r['elapsedSeconds'],'clientRetryEvents':r.get('retryEvents',sum(e['type']=='llm/retry' for e in r['events'])),'retryCodes':[e['data']['failure']['code'] for e in r['events'] if e['type']=='llm/retry'],'persistedPromptMatches':r['persistedPromptMatches'],'promptSHA256':r['promptSHA256'],'warming':w,'preWarmingElapsedSeconds':(admitted-start).total_seconds(),'firstOutputUTC':first.isoformat() if first else None,'sessionStats':current_stats,'sessionStatsCumulative':r['projection']['sessionStats'],'sessionStatsBaseline':baseline or {},'sessionStatsScope':'Current turn; cumulative counters minus verified same-session baseline','shortReplies':shorts,'strictlyOverlappingAdmittedShortReplies':len(live),'admittedShortMinimumSeconds':min(s['seconds'] for s in live),'admittedShortMaximumSeconds':max(s['seconds'] for s in live),'generationShortReplies':sum(s['duringGeneration'] for s in live),'modelBefore':c['before']['pods'],'modelAfter':c['samples'][-1]['pods'],'modelUnchanged':c['before']['pods']==c['samples'][-1]['pods'],'sharedModelLogSignaturesDuringAdmittedPhase':{x:text.count(x) for x in signatures},'minimumSampledFreeMiB':min(g['freeMiB'] for sample in c['samples'] for g in sample.get('gpus',[])),'warmingLifecycleEvents':warms,'interpretationLimitations':'Warm-phase attribution is correlated by exact final input count and timestamps, not a globally unique request ID. Shared-model warnings are time-window observations. Idle metric samples alone do not establish admission availability.'}
(p/'performance-summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps({k:summary[k] for k in ['usage','totalElapsedSeconds','clientRetryEvents','preWarmingElapsedSeconds','strictlyOverlappingAdmittedShortReplies','admittedShortMinimumSeconds','admittedShortMaximumSeconds','generationShortReplies','modelUnchanged','sharedModelLogSignaturesDuringAdmittedPhase']}))
