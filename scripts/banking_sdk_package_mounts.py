"""Source-pinned banking SDK package inputs; no discovery, Secret, write or model calls.

Only these existing immutable ConfigMaps in the observed namespace are trusted.
A qualification Pod's mounts are never implicitly inherited by child workers.
"""
import base64
import copy
import hashlib
import json

PACKAGE_ANNOTATION = 'dsh.example.com/sdk-package-input-contract-sha256'


def _expected():
    return {'kind':'DSH_BANKING_SDK_PACKAGE_INPUTS_V1',
        'namespace':'llm','namespaceUID':'561ca46a-94b7-4f25-8589-521241bfb73f',
        'packageAdmissionSha256':'0911a5110d53a602f4b7975f36c48282d3c28f46f3461529166fb4b04858fceb',
        'inputs':[
            {'role':'admission','name':'c3-f10-admission-0911a5110d53','uid':'bfa1628f-aaa0-4590-a523-ea0f6d203385',
             'key':'official-sdk-package.json','encoding':'data','sha256':'0911a5110d53a602f4b7975f36c48282d3c28f46f3461529166fb4b04858fceb',
             'volume':'banking-sdk-admission','mountPath':'/etc/dsh-native-admission/official-sdk-package.json'},
            {'role':'wheel','name':'c3-f10-wheel-953e57ccc77e','uid':'50cf3e3a-add9-4d2b-965c-2aaef5b9e503',
             'key':'deepseek_harness_sdk-0.2.2a2-py3-none-any.whl','encoding':'binaryData','sha256':'953e57ccc77eea412c709373c99f26e647986c1dced4ca707a6d8c440b975492',
             'volume':'banking-sdk-wheel','mountPath':'/packages/approved/python/deepseek_harness_sdk-0.2.2a2-py3-none-any.whl'}]}


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def package_inputs(*,namespace,namespace_uid,admission_sha256):
    value=_expected()
    if (namespace,namespace_uid,admission_sha256)!=(value['namespace'],value['namespaceUID'],value['packageAdmissionSha256']):
        raise ValueError('EXACT_BANKING_PACKAGE_NAMESPACE_AND_ADMISSION_REQUIRED')
    return value


def validate_contract(value):
    if not isinstance(value,dict) or _canonical(value)!=_canonical(_expected()):
        raise ValueError('SOURCE_PINNED_BANKING_PACKAGE_INPUTS_REQUIRED')
    return copy.deepcopy(value)


def contract_sha256(value):
    return hashlib.sha256(_canonical(validate_contract(value))).hexdigest()


def package_map_names():
    return tuple(item['name'] for item in _expected()['inputs'])


def validate_package_map(value,item):
    expected=_expected()
    if not isinstance(item,dict) or not any(_canonical(item)==_canonical(x) for x in expected['inputs']):
        raise ValueError('UNREVIEWED_BANKING_PACKAGE_REFERENCE')
    if not isinstance(value,dict):raise ValueError('BANKING_PACKAGE_CONFIGMAP_REQUIRED')
    meta=value.get('metadata',{})
    if (value.get('apiVersion')!='v1' or value.get('kind')!='ConfigMap' or value.get('immutable') is not True
            or meta.get('namespace')!=expected['namespace'] or meta.get('name')!=item['name'] or meta.get('uid')!=item['uid']
            or meta.get('deletionTimestamp') or not isinstance(meta.get('resourceVersion'),str) or not meta['resourceVersion']):
        raise ValueError('BANKING_IMMUTABLE_PACKAGE_IDENTITY_REFUSED')
    data=value.get(item['encoding'],{})
    other='binaryData' if item['encoding']=='data' else 'data'
    if not isinstance(data,dict) or set(data)!={item['key']} or value.get(other,{}) not in ({},None):
        raise ValueError('EXACT_BANKING_PACKAGE_CONFIGMAP_KEYS_REQUIRED')
    text=data[item['key']]
    if not isinstance(text,str) or len(text)>12*1024*1024:raise ValueError('BOUNDED_BANKING_PACKAGE_DATA_REQUIRED')
    try:raw=text.encode('utf-8') if item['encoding']=='data' else base64.b64decode(text,validate=True)
    except (ValueError,UnicodeError):raise ValueError('BANKING_PACKAGE_ENCODING_REFUSED') from None
    if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('BANKING_PACKAGE_CONTENT_HASH_REFUSED')
    return {'name':item['name'],'uid':item['uid'],'sha256':item['sha256'],'bytes':len(raw)}


def mount_package_inputs(pod,*,namespace_uid,admission_sha256):
    contract=package_inputs(namespace=pod['metadata']['namespace'],namespace_uid=namespace_uid,admission_sha256=admission_sha256)
    result=copy.deepcopy(pod)
    worker=result['spec']['containers'][0]
    if worker['name']!='worker':raise ValueError('EXACT_BANKING_PACKAGE_WORKER_REQUIRED')
    annotations=result['metadata'].setdefault('annotations',{})
    if PACKAGE_ANNOTATION in annotations:raise ValueError('BANKING_PACKAGE_ANNOTATION_INJECTION_REFUSED')
    for item in contract['inputs']:
        if any(v['name']==item['volume'] for v in result['spec']['volumes']):raise ValueError('BANKING_PACKAGE_VOLUME_INJECTION_REFUSED')
        for mount in worker['volumeMounts']:
            path=mount['mountPath'].rstrip('/')
            if path==item['mountPath'] or item['mountPath'].startswith(path+'/') or path.startswith(item['mountPath']+'/'):
                raise ValueError('BANKING_PACKAGE_MOUNT_PATH_INJECTION_REFUSED')
        result['spec']['volumes'].append({'name':item['volume'],'configMap':{'name':item['name'],'defaultMode':0o444,'items':[{'key':item['key'],'path':item['key']}]}})
        worker['volumeMounts'].append({'name':item['volume'],'mountPath':item['mountPath'],'subPath':item['key'],'readOnly':True})
    annotations[PACKAGE_ANNOTATION]=contract_sha256(contract)
    return result
