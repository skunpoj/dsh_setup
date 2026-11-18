"""Personal-only provider proof contract. References are not secret values.

Protected policy issuer must verify the actual request route/project/principal,
linked personal billing, quota and rates from retained authoritative evidence.
Internal/on-prem naming or a browser login is never such evidence.
"""

def require_personal_billing(proof,*,clock):
    keys={'provider','personalAccount','requestProject','principal','credentialRoute',
        'linkedBillingDestination','quotaEvidenceReference','ratesEvidenceReference',
        'billingEvidenceReference','personalOnlyVerified','expiresAt'}
    if (not isinstance(proof,dict) or set(proof)!=keys or proof.get('personalOnlyVerified') is not True
            or type(proof.get('expiresAt')) not in (int,float) or not 0<proof['expiresAt']-clock()<=300
            or any(not isinstance(proof[k],str) or not proof[k] or len(proof[k])>512 for k in keys-{'personalOnlyVerified','expiresAt'})):
        raise ValueError('PERSONAL_PROVIDER_BILLING_PROJECT_PRINCIPAL_QUOTA_RATES_REQUIRED')
    if proof['provider'].lower() in {'google','gcp','gemini'} and proof['personalAccount']!='skunpoj@gmail.com':
        raise ValueError('INTENDED_PERSONAL_GOOGLE_ACCOUNT_REQUIRED')
    return dict(proof)


def require_provider_authorization(proof, *, clock):
    """Protected issuer supplies either personal proof or the narrow human exception.

    This validates retained authorization fields, never investigates billing.
    The protected approval hash is bound by the immutable banking descriptor.
    """
    if isinstance(proof,dict) and 'scopedOnPremApproval' in proof:
        value=proof['scopedOnPremApproval']
        from scripts.banking_standing_authority import standing
        is_standing=standing(value)
        keys={'kind','authorizationReference','routeReceiptSha256','backend','namespace','runtimes','totalRequests','maxRequestsPerTask','expiresAt'}
        if is_standing:keys=keys|{'standingAuthority'}
        if (not isinstance(value,dict) or set(value)!=keys
                or value['kind']!='DSH_EXPLICIT_ONPREM_BANKING_AUTHORIZATION_V1'
                or value['authorizationReference']!='A2A-CODEX-C4-EXPLICIT-HUMAN-ONPREM-BANKING-BACKEND-AUTHORIZATION-20261111'
                or value['routeReceiptSha256']!='f777d26d1e123683aeb03da3f4d62d4ed5b5d69cd52629fc5a90c1fcbd85f815'
                or value['backend']!='deepinfer-dspark' or value['namespace']!='llm'
                or value['runtimes']!=['claude','deepagents','sdk']
                or not (is_standing and value['totalRequests'] is None or not is_standing and type(value['totalRequests']) is int and value['totalRequests']==240)
                or not (is_standing and value['maxRequestsPerTask'] is None or not is_standing and type(value['maxRequestsPerTask']) is int and value['maxRequestsPerTask']==32)
                or not (is_standing and value['expiresAt'] is None or not is_standing and type(value['expiresAt']) in (int,float) and 0<value['expiresAt']-clock()<=300)):
            raise ValueError('EXPLICIT_SCOPED_ONPREM_BANKING_AUTHORIZATION_REQUIRED')
        return 'scopedOnPremApproval',dict(value)
    return 'personalBilling',require_personal_billing(proof.get('personalBilling') if isinstance(proof,dict) else None,clock=clock)
