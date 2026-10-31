"""Reject accidental ingress isolation of pre-existing shared services."""


def matches(selector, labels):
    if any(labels.get(k)!=v for k,v in selector.get('matchLabels',{}).items()):return False
    for item in selector.get('matchExpressions',[]):
        key,operation=item['key'],item['operator'];values=item.get('values',[])
        if operation=='In' and labels.get(key)not in values:return False
        if operation=='NotIn' and key in labels and labels[key]in values:return False
        if operation=='Exists' and key not in labels:return False
        if operation=='DoesNotExist' and key in labels:return False
        if operation not in ['In','NotIn','Exists','DoesNotExist']:raise ValueError('Unknown label operation')
    return True


def guard(policies, baseline, workloads, own_targets):
    protected=0
    for workload in workloads:
        labels=workload.get('spec',{}).get('template',{}).get('metadata',{}).get('labels',workload['metadata'].get('labels',{}))
        if workload['metadata']['name']in own_targets or labels.get('app')in own_targets:continue
        for policy in policies:
            spec=policy['spec']
            if 'Ingress'not in spec.get('policyTypes',['Ingress'])or not matches(spec.get('podSelector',{}),labels):continue
            already_isolated=any('Ingress'in old['spec'].get('policyTypes',['Ingress'])and matches(old['spec'].get('podSelector',{}),labels)for old in baseline)
            if not already_isolated:raise ValueError('New policy would isolate ingress for an existing workload; preserve the shared service boundary')
            protected+=1
    return {'passed':True,'existingSelectedTargetsReviewed':protected}
