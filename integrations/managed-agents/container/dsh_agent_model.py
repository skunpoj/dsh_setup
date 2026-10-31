"""Managed model for Deep Agents. No user-selected provider, endpoint or credential."""
import json, os, stat
from pathlib import Path
from urllib.parse import urlsplit
from langchain_openai import ChatOpenAI
from httpx import Client, AsyncClient
MODEL='deepseek-v4.1-flash'
POLICY=Path('/opt/dsh/config/managed-agents.json')
TOKEN=Path('/harness-credentials/api-key')
def validate_policy(doc):
 if not isinstance(doc,dict) or doc.get('model')!=MODEL: raise ValueError('DSH model policy invalid')
 u=urlsplit(doc.get('base_url',''))
 if u.scheme not in ('http','https') or u.username or u.password or u.port!=4000 or u.path!='/v1' or u.query or u.fragment: raise ValueError('DSH gateway policy invalid')
 host=u.hostname or ''
 parts=host.split('.')
 if len(parts)!=5 or parts[0]!='litellm' or parts[2:]!=['svc','cluster','local'] or not parts[1] or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in parts[1]): raise ValueError('DSH gateway host invalid')
 return {'model':MODEL,'base_url':doc['base_url']}
def load_policy():
 s=POLICY.stat()
 if POLICY.is_symlink() or s.st_uid!=0 or s.st_mode & 0o022 or not stat.S_ISREG(s.st_mode) or s.st_size>4096: raise ValueError('Read-only operator policy required')
 return validate_policy(json.loads(POLICY.read_text()))
def checked_options(options,policy):
 options=dict(options)
 if options.pop('model',MODEL)!=MODEL: raise ValueError('DSH model is locked')
 if 'base_url' in options and options.pop('base_url')!=policy['base_url']: raise ValueError('DSH endpoint is locked')
 if options.pop('bypass_auth',True) is not True: raise ValueError('DSH credentials are managed')
 if 'api_key' in options: raise ValueError('DSH credential override denied')
 allowed={'temperature','max_tokens','timeout','max_retries','streaming','stream_usage'}
 if set(options)-allowed: raise ValueError('DSH model option denied')
 bounds={'temperature':(0,2),'max_tokens':(1,8192),'timeout':(1,3600),'max_retries':(0,2)}
 for k,(lo,hi) in bounds.items():
  if k in options and (isinstance(options[k],bool) or not isinstance(options[k],(int,float)) or not lo<=options[k]<=hi): raise ValueError('DSH model option bound')
 for k in ['streaming','stream_usage']:
  if k in options and type(options[k]) is not bool: raise ValueError('DSH streaming option invalid')
 return options
class DSHManagedChat(ChatOpenAI):
 def __init__(self,**kwargs):
  policy=load_policy();options=checked_options(kwargs,policy)
  key=TOKEN.read_text().strip()
  if not key or len(key)>8192: raise ValueError('DSH runtime credential unavailable')
  fixed={'model':MODEL,'base_url':policy['base_url'],'api_key':key,'use_responses_api':False,'max_retries':1,'temperature':0,'max_tokens':8192,'timeout':3600,'extra_body':{'chat_template_kwargs':{'enable_thinking':False}}}
  fixed.update(options)
  fixed['http_client']=Client(trust_env=False)
  fixed['http_async_client']=AsyncClient(trust_env=False)
  super().__init__(**fixed)
