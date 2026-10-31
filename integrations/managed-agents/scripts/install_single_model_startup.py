from pathlib import Path
p=Path('/usr/local/bin/start-dsh')
s=p.read_text()
a='node /opt/dsh/scripts/configure_workspace_policy.js /state'
if s.count(a)!=1:raise SystemExit('Unreviewed start-dsh anchor; refusing to patch')
s=s.replace(a,a+'\nnode /opt/dsh/scripts/enforce_single_model_profiles.mjs /state')
p.write_text(s)
