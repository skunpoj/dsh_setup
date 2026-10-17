"""Separate a review turn's counters from cumulative DSH session counters."""


def turn_stats(result, baseline=None):
    cumulative = result['projection']['sessionStats']
    baseline = result.get('baselineSessionStats', baseline)
    if result.get('continuedSession') and not baseline:
        raise ValueError('Continuation requires a verified same-session baseline')
    baseline = baseline or {}
    delta = {}
    for key, value in cumulative.items():
        if not isinstance(value, (int, float)) or not isinstance(baseline.get(key, 0), (int, float)):
            raise ValueError('Unexpected session counter type')
        delta[key] = value-baseline.get(key, 0)
        if delta[key] < 0: raise ValueError('Session counters decreased; baseline does not match')
    return delta
