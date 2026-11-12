"""Exact protected standing authority for the three named banking routes only."""
AUTHORITY = dict(kind='DSH_STANDING_BANKING_AUTHORITY_V1', authorizationReference='A2A-CODEX-C4-HUMAN-LIFTS-BUDGET-EXPIRY-REQUIREMENT', backend='deepinfer-dspark', namespace='llm', runtimes=['claude','deepagents','sdk'])
def standing(value):
    return isinstance(value,dict) and value.get('standingAuthority')==AUTHORITY

def valid_cap(value):
    return value is None or type(value) is int and 2<=value<=32

def valid_expiry(value,clock):
    return value is None or type(value) in (int,float) and 0<value-clock()<=300
