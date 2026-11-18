"""Protected ordinary-broker banking startup. Disabled without explicit files.

No environment flag/caller module/credential discovery/native scope replacement.
Actual identities, policy approvals and qualification receipt must be supplied
by the authorized owner. Missing/null/unverified inputs refuse; no fallback.
"""
import base64,hashlib,os,ssl,stat,time
from pathlib import Path
from scripts.banking_sdk_scope_factory import unique_json,digest,install_banking_service
from scripts.banking_sdk_worker_api import BankingWorkerAPI
from scripts.banking_sdk_kubernetes_backend import KubernetesBankingBackend
from scripts.official_sdk_package_admission import verify_sdk_admission
from scripts.official_sdk_deployment_observer import exact_running_digest
from scripts.unattended_model_guard import APPROVED_UPSTREAM
from scripts import banking_allowance
from scripts.banking_sdk_billing_policy import require_provider_authorization

DESCRIPTOR='/etc/dsh/banking-sdk-scope.json'
POLICY='/etc/dsh/banking-sdk-backend.json'
INTEGRATION='/etc/dsh/banking-sdk-integration.json'
QUALIFICATION='/etc/dsh/banking-sdk-qualification.json'
PROVIDER='/etc/dsh/banking-sdk-provider-approval.json'
STORAGE='/etc/dsh/banking-sdk-storage-approval.json'
CA='/etc/dsh-banking-api-identity/ca.crt'
TOKEN='/run/dsh-banking-api-identity/token'
SELF_UID='/etc/dsh-banking-identity/pod-uid'
STATE='/state/banking-guard-protected/controller'
ALLOWANCE='/etc/dsh/banking-allowance.json'
GLOBAL_LEDGER='/state/banking-guard-protected/global/allowance-ledger.json'
BANKING_BOOTSTRAP_CAPABILITY='C3_BANKING_CLI_HOLD_AND_BOUND_NATIVE_SDK_PASS_V1'


def protected_bytes(path,limit=1048576):
    # Kubernetes atomic-writer projections use symlinks within a root-owned mount.
    # Resolve only these fixed identity mounts, never arbitrary caller paths.
    fixed_roots=('/etc/dsh-banking-api-identity','/run/dsh-banking-api-identity','/etc/dsh-banking-identity')
    candidate=Path(path)
    for mount in fixed_roots:
        root=Path(mount)
        if candidate.parent==root:
            info=root.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:raise ValueError('PROTECTED_IDENTITY_MOUNT_REQUIRED')
            resolved=candidate.resolve(strict=True)
            if not resolved.is_relative_to(root.resolve()):raise ValueError('PROJECTED_IDENTITY_ESCAPE_REFUSED')
            for parent in resolved.parents:
                if parent==root:break
                info=parent.lstat()
                if not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022:raise ValueError('PROTECTED_PROJECTION_PARENT_REQUIRED')
            path=resolved
            break
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode&0o022 or info.st_size>limit:raise ValueError('PROTECTED_BANKING_INPUT_REQUIRED')
        with os.fdopen(fd,'rb',closefd=False) as stream:data=stream.read(limit+1)
        if len(data)>limit:raise ValueError('BANKING_INPUT_SIZE_LIMIT')
        return data
    finally:os.close(fd)


roles={'scope':['banking_sdk_scope_factory.py','official_sdk_banking_guard.py','banking_allowance.py','banking_standing_authority.py','agent_runtime_commands.py'],
    'controller':['banking_sdk_kubernetes_backend.py','banking_sdk_worker_api.py','banking_sdk_worker_stream.py','banking_sdk_worker.py','banking_sdk_package_mounts.py','banking_sdk_worker_entry.py','a2a_sdk_worker.py','a2a_sdk_transport.py','banking_sdk_tool_policy.mjs'],
    'runner':['official_sdk_session.py','official_sdk_control_peer.py'],
    'guard':['banking_sdk_guard_ledger.py','unattended_model_guard.py'],
    'backend':['banking_sdk_bootstrap.py','banking_sdk_seed_contract.py','banking_sdk_billing_policy.py','banking_sdk_state_init.py','banking_sdk_identity_init.py','banking_process_identity.py','banking_history_view.py','banking_private_capture.py']}
def banking_source_inventory(*,reader=protected_bytes):
    result={role:digest({name:hashlib.sha256(reader('/opt/dsh/scripts/'+name,1048576)).hexdigest() for name in paths}) for role,paths in roles.items()}
    result['controller']=digest(dict(modules=result['controller'],entries={name:hashlib.sha256(reader('/opt/dsh/container/'+name,1048576)).hexdigest() for name in ('dsh-banking-controller-entry.py','dsh-unattended.py','start-dsh.sh','dsh-sdk-control.py','dsh-task-broker.py','dsh-banking-sdk-guard.py')}))
    result['controller']=digest(dict(modules=result['controller'],policyProfile=hashlib.sha256(reader('/opt/dsh/config/banking-sdk-tool-policy.patch.yml',1048576)).hexdigest()))
    # Sidecar entry participates in the guard role too.
    result['guard']=digest(dict(modules=result['guard'],entry=hashlib.sha256(reader('/opt/dsh/container/dsh-banking-sdk-guard.py',1048576)).hexdigest()))
    return result

def configure(server,registry,*,workspace_root='/workspace',reader=protected_bytes,api_factory=BankingWorkerAPI,
              backend_factory=KubernetesBankingBackend,package_check=verify_sdk_admission,clock=time.time,
              owner_check=True,state_root=STATE,allowance_file=ALLOWANCE,ledger_file=GLOBAL_LEDGER,tls_factory=ssl.create_default_context):
    try:raw=reader(DESCRIPTOR,65536)
    except FileNotFoundError:return False
    server.sdk_banking_required=True
    descriptor=unique_json(raw);policy=unique_json(reader(POLICY,65536));integration=unique_json(reader(INTEGRATION,65536))
    if not isinstance(descriptor,dict) or descriptor.get('mode')!='banking' or digest(policy)!=descriptor.get('backendPolicySha256'):
        raise ValueError('EXACT_BANKING_STARTUP_POLICY_REQUIRED')
    if not isinstance(integration,dict) or set(integration)!={'apiOrigin','apiAudience','controllerServiceAccountUID','controllerRefs','controllerContainer'} or set(integration['controllerRefs'])!={'Pod','ReplicaSet','Deployment'}:
        raise ValueError('EXACT_BANKING_INTEGRATION_REFERENCES_REQUIRED')
    qualification_raw=reader(QUALIFICATION,65536);qualification=unique_json(qualification_raw)
    expected=dict(kind='DSH_OFFICIAL_SDK_QUALIFICATION_ACCEPTANCE_V1',status='PASS',sourceCommit=descriptor['sourceCommit'],imageDigest=descriptor['imageDigest'],packageAdmissionSha256=descriptor['packageAdmissionSha256'],cases={'L3':'PASS','L6':'PASS','L9':'PASS'},modelStarts=0)
    held_expected=dict(expected,status='HOLD',cases={'L3':'HOLD','L6':'HOLD','L9':'HOLD'})
    sdk_held=qualification==held_expected
    if type(qualification.get('modelStarts')) is not int or (qualification!=expected and not sdk_held) or hashlib.sha256(qualification_raw).hexdigest()!=descriptor.get('qualificationReceiptSha256'):
        raise ValueError('EXACT_IMAGE_SDK_QUALIFICATION_REQUIRED')
    if package_check().get('admissionSha256')!=descriptor['packageAdmissionSha256']:raise ValueError('BANKING_OFFICIAL_PACKAGE_CHANGED')
    ca=reader(CA,1048576).decode('ascii');tls=tls_factory(cadata=ca)
    def authorization():
        token=reader(TOKEN,16384).decode('ascii').strip()
        parts=token.split('.')
        if len(parts)!=3:raise ValueError('BOUND_BANKING_CONTROLLER_TOKEN_REQUIRED')
        claims=unique_json(base64.urlsafe_b64decode(parts[1]+'='*((-len(parts[1]))%4)))
        kube=claims.get('kubernetes.io',{}) if isinstance(claims,dict) else {}
        audience=claims.get('aud') if isinstance(claims,dict) else None
        audiences=[audience] if isinstance(audience,str) else audience
        if (claims.get('sub')!='system:serviceaccount:llm:dsh-banking-sdk-controller'
                or type(claims.get('exp')) not in (int,float) or claims['exp']<=clock()
                or not isinstance(audiences,list) or integration['apiAudience'] not in audiences
                or kube.get('namespace')!='llm' or kube.get('serviceaccount',{}).get('name')!='dsh-banking-sdk-controller'
                or kube['serviceaccount'].get('uid')!=integration['controllerServiceAccountUID']
                or kube.get('pod',{}).get('uid')!=reader(SELF_UID,128).decode().strip()):
            raise ValueError('BANKING_CONTROLLER_TOKEN_SUBJECT_POD_AUDIENCE_REFUSED')
        # The TLS Kubernetes API independently authenticates the signature.
        return 'Bearer '+token
    api=api_factory(origin=integration['apiOrigin'],tls_context=tls,authorization=authorization,
        namespace=policy['namespace'],namespace_uid=policy['namespaceUID'],allowed_accounts={'dsh-banking-sdk-controller':integration['controllerServiceAccountUID'],policy['serviceAccount']:policy['serviceAccountUID']},allowed_claims={policy['workspaceClaim']:policy['workspaceClaimUID'],policy['guardClaim']:descriptor['storage']['claimUID']},controller_refs=integration['controllerRefs'],admission=descriptor,policy=policy,reservation_validator=lambda id:banking_allowance._read(Path(ledger_file)).get(id))
    def placement():
        namespace=api.read_namespace();api.read_account('dsh-banking-sdk-controller');pod=api.read_reference('Pod');rs=api.read_reference('ReplicaSet');deployment=api.read_reference('Deployment')
        own_uid=reader(SELF_UID,128).decode().strip()
        def owner(value,kind,name,uid):
            rows=[x for x in value['metadata'].get('ownerReferences',[]) if x.get('controller') is True]
            return len(rows)==1 and rows[0].get('kind')==kind and rows[0].get('name')==name and rows[0].get('uid')==uid
        if pod['metadata']['uid']!=own_uid or not owner(pod,'ReplicaSet',rs['metadata']['name'],rs['metadata']['uid']) or not owner(rs,'Deployment',deployment['metadata']['name'],deployment['metadata']['uid']):raise ValueError('BANKING_EXECUTING_CONTROLLER_IDENTITY_CHANGED')
        for resource in (pod,deployment):
            labels=resource['metadata'].get('labels',{})
            if labels.get('dsh.example.com/runtime-environment')!='test' or labels.get('dsh.example.com/runtime-purpose')!='banking':raise ValueError('BANKING_CONTROLLER_CLASSIFICATION_UNVERIFIED')
        if pod['spec'].get('nodeName')!=policy['nodeName']:raise ValueError('BANKING_RWO_CONTROLLER_WORKER_NODE_MISMATCH')
        if pod['spec'].get('serviceAccountName')!='dsh-banking-sdk-controller':raise ValueError('BANKING_CONTROLLER_ACCOUNT_REFUSED')
        name=integration['controllerContainer'];containers=[x for x in pod.get('spec',{}).get('containers',[]) if x.get('name')==name];statuses=[x for x in pod.get('status',{}).get('containerStatuses',[]) if x.get('name')==name]
        if len(containers)!=1 or containers[0].get('image','').split('@')[-1]!='sha256:'+descriptor['imageDigest']:raise ValueError('BANKING_EXECUTING_IMAGE_UNVERIFIED')
        if not statuses:raise ValueError('BANKING_INITIAL_RUNNING_STATUS_PENDING')
        if len(statuses)!=1 or statuses[0].get('restartCount')!=0:raise ValueError('BANKING_EXECUTING_IMAGE_UNVERIFIED')
        status=statuses[0]
        if status.get('imageID') and exact_running_digest(status['imageID'])!='sha256:'+descriptor['imageDigest']:raise ValueError('BANKING_EXECUTING_IMAGE_UNVERIFIED')
        if status.get('state',{}).get('terminated'):raise ValueError('BANKING_EXECUTING_IMAGE_UNVERIFIED')
        if not status.get('imageID') or not status.get('state',{}).get('running'):raise ValueError('BANKING_INITIAL_RUNNING_STATUS_PENDING')
        return dict(namespace=api.namespace,namespaceUID=namespace['metadata']['uid'],controllerPodUID=own_uid,workloadUID=deployment['metadata']['uid'],environment='test',workloadRole='banking')
    def provider_policy(provider_ref,billing_ref):
        approval_raw=reader(PROVIDER,65536);approval=unique_json(approval_raw)
        if not isinstance(approval,dict) or set(approval) not in ({'kind','billingAuthorizationReference','expiresAt','route','personalBilling'},{'kind','billingAuthorizationReference','expiresAt','route','scopedOnPremApproval'}) or approval.get('kind')!='DSH_BANKING_PROVIDER_APPROVAL_V1' or provider_ref!='sha256:'+hashlib.sha256(approval_raw).hexdigest() or approval.get('billingAuthorizationReference')!=billing_ref or (approval.get('expiresAt') is not None and approval.get('expiresAt',0)<=clock()):raise ValueError('BANKING_PROVIDER_APPROVAL_UNBOUND')
        route=approval.get('route')
        if not isinstance(route,dict) or 'providerPolicyReference' in route:raise ValueError('BANKING_PROVIDER_ROUTE_SCHEMA_REFUSED')
        authorization_kind,authorization=require_provider_authorization(approval,clock=clock)
        result=dict(route,providerPolicyReference=provider_ref,**{authorization_kind:authorization})
        expected_route=dict(**{authorization_kind:authorization},providerPolicyReference=provider_ref,billingAuthorizationReference=billing_ref,verified=True,upstream=APPROVED_UPSTREAM,credentialSecret=policy['credentialSecret'],namespace=policy['namespace'])
        if result.get('verified') is not True or result!=expected_route:raise ValueError('BANKING_PROVIDER_BILLING_ROUTE_NOT_VERIFIED')
        return result
    storage=unique_json(reader(STORAGE,65536))
    if not isinstance(storage,dict) or storage.get('persistent') is not True or storage.get('agentMountAccess') is not False or storage.get('supportedPosixLocks') is not True or storage!={'kind':'DSH_BANKING_PROTECTED_STORAGE_APPROVAL_V1','storage':descriptor['storage'],'persistent':True,'agentMountAccess':False,'supportedPosixLocks':True}:
        raise ValueError('BANKING_PROTECTED_STORAGE_APPROVAL_REQUIRED')
    # Each source role is a hash of a fixed protected source inventory. No user path.
    source_observer=lambda:banking_source_inventory(reader=reader)
    deadline=time.monotonic()+15
    while True:
        try:
            observed_placement=placement()
            break
        except ValueError as error:
            if str(error)!='BANKING_INITIAL_RUNNING_STATUS_PENDING' or time.monotonic()>=deadline:raise
            time.sleep(.1)  # same own-Pod GET only, before any task/model admission
    if sdk_held:
        # Independent CLI tasks retain their own protected allowance/route
        # admission. HOLD is never SDK acceptance and cannot fall back locally.
        from scripts.banking_sdk_scope_factory import BankingSDKScope
        validator=BankingSDKScope.__new__(BankingSDKScope);validator.clock=clock
        validator._validate(descriptor,allow_expired=True)
        if observed_placement!=descriptor['placement'] or source_observer()!=descriptor['sourceHashes']:raise ValueError('HELD_CONTROLLER_BINDING_CHANGED')
        server.sdk_service=None
        return False
    backend=backend_factory(api=api,admission=descriptor,policy=policy,state_root=state_root,placement_observer=placement,provider_policy_verifier=provider_policy,clock=clock,owner_check=owner_check)
    return install_banking_service(server,descriptor_reader=lambda:unique_json(reader(DESCRIPTOR,65536)),backend=backend,task_lookup=registry.get,state_root=state_root,source_observer=source_observer,workspace_root=workspace_root,allowance_file=allowance_file,ledger_file=ledger_file,clock=clock,owner_check=owner_check,admission_check=package_check)
