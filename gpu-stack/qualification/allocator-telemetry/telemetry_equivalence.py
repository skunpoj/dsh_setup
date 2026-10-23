"""Strict, read-only proof of one optional allocator-telemetry source delta.

This module performs no cluster, inference, process, GPU or filesystem mutation.
It is not permission to accept a numerical change or to replay a capacity test.
"""
from pathlib import Path
import copy
import hashlib
import json
import re

SCOPE = 'read-only-periodic-native-allocator-counters'
SOURCE = 'model_executor/allocator_observer.py'
FLAG = 'DSH_QUALIFICATION_PERIODIC_READONLY_COUNTERS'
ANNOTATION = 'dsh-qualification/periodic-counters'
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


def _require(condition, message):
    if not condition:
        raise RuntimeError(message)


def _digest(value):
    return type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, 'Duplicate JSON key')
        result[key] = value
    return result


def _invalid_constant(value):
    raise RuntimeError('Non-finite JSON value')


def _read(path):
    try:
        with Path(path).open('rb') as stream:
            raw = stream.read(MAX_ARTIFACT_BYTES + 1)
        _require(len(raw) <= MAX_ARTIFACT_BYTES, 'Artifact exceeds bounded size')
        value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique,
                           parse_constant=_invalid_constant)
    except (OSError, UnicodeError, ValueError, TypeError) as error:
        raise RuntimeError('Artifact cannot be read as strict JSON') from error
    _require(type(value) is dict, 'JSON object artifact required')
    return value, hashlib.sha256(raw).hexdigest()


def _artifact(proof, key):
    reference = proof.get(key)
    _require(type(reference) is dict and set(reference) == {'path', 'sha256'},
             'Exact path/SHA256 artifact reference required: ' + key)
    _require(type(reference['path']) is str and reference['path'], 'Artifact path missing')
    _require(_digest(reference['sha256']), 'Artifact SHA256 invalid')
    document, actual = _read(reference['path'])
    _require(actual == reference['sha256'], 'Artifact hash differs: ' + key)
    return document


def _single(items, name, label):
    _require(type(items) is list, 'Expected list: ' + label)
    matches = [item for item in items if type(item) is dict and item.get('name') == name]
    _require(len(matches) == 1, 'Exactly one ' + name + ' required: ' + label)
    return matches[0]


def _spec(document):
    # Existing qualification artifacts contain the Deployment spec directly.
    # Whole Deployment artifacts are also compared without discarding metadata.
    if 'template' in document:
        return document
    _require(document.get('kind') == 'Deployment' and type(document.get('spec')) is dict,
             'Deployment specification artifact required')
    return document['spec']


def verify(old_sources, new_sources, proof_path):
    """Return None if sources match; otherwise validate only the permitted delta.

    Proof keys: scope, changedSource, oldObserverSHA256, newObserverSHA256,
    oldCM/newCM/oldSpec/newSpec, each artifact reference {path, sha256}.
    """
    _require(type(old_sources) is dict and type(new_sources) is dict, 'Source maps required')
    for mapping in (old_sources, new_sources):
        _require(all(type(key) is str and _digest(value) for key, value in mapping.items()),
                 'Source map entries must be exact path/SHA256 strings')
    if old_sources == new_sources:
        return None
    _require(set(old_sources) == set(new_sources), 'Source key sets differ')
    changed = [key for key in old_sources if old_sources[key] != new_sources[key]]
    _require(changed == [SOURCE], 'Only the allocator observer source may change')
    _require(proof_path is not None, 'Bound telemetry proof required')
    proof, proof_hash = _read(proof_path)
    _require(proof.get('scope') == SCOPE and proof.get('changedSource') == SOURCE,
             'Telemetry proof scope/source differs')
    _require(proof.get('oldObserverSHA256') == old_sources[SOURCE] and
             proof.get('newObserverSHA256') == new_sources[SOURCE],
             'Observer hashes differ from bound source maps')

    old_cm = _artifact(proof, 'oldCM')
    new_cm = _artifact(proof, 'newCM')
    for cm in (old_cm, new_cm):
        _require(cm.get('apiVersion') == 'v1' and cm.get('kind') == 'ConfigMap',
                 'ConfigMap artifact required')
        _require(cm.get('immutable') is True, 'Immutable ConfigMap required')
        _require(type(cm.get('metadata')) is dict and
                 type(cm['metadata'].get('name')) is str and cm['metadata']['name'],
                 'Named ConfigMap required')
        _require(type(cm.get('data')) is dict and
                 all(type(k) is str and type(v) is str for k, v in cm['data'].items()),
                 'ConfigMap data must be exact strings')
    old_name, new_name = old_cm['metadata']['name'], new_cm['metadata']['name']
    _require(old_name != new_name, 'A separate telemetry ConfigMap name is required')
    _require(old_cm['metadata'].get('namespace') == new_cm['metadata'].get('namespace'),
             'ConfigMap namespace changed')
    _require(set(old_cm['data']) == set(new_cm['data']) and 'allocator_observer.py' in old_cm['data'],
             'ConfigMap source key sets differ')
    _require(_canonical(old_cm.get('binaryData')) == _canonical(new_cm.get('binaryData')),
             'ConfigMap binary source data changed')
    for key in old_cm['data']:
        if key != 'allocator_observer.py':
            _require(old_cm['data'][key] == new_cm['data'][key], 'Other ConfigMap source changed: ' + key)
    for cm, expected_hash in ((old_cm, old_sources[SOURCE]), (new_cm, new_sources[SOURCE])):
        _require(hashlib.sha256(cm['data']['allocator_observer.py'].encode('utf-8')).hexdigest()
                 == expected_hash, 'ConfigMap observer bytes do not match source hash')

    old_spec = _artifact(proof, 'oldSpec')
    new_spec = _artifact(proof, 'newSpec')
    expected = copy.deepcopy(old_spec)
    try:
        template = _spec(expected)['template']
        pod = template['spec']
        volume = _single(pod['volumes'], 'allocator-patch', 'volumes')
        _require(volume['configMap']['name'] == old_name, 'Old allocator ConfigMap reference differs')
        volume['configMap']['name'] = new_name
        container = _single(pod['containers'], 'vllm', 'containers')
        env = container.setdefault('env', [])
        _require(type(env) is list and all(type(item) is dict for item in env), 'Invalid vllm env')
        _require(not any(item.get('name') == FLAG for item in env), 'Sampler flag already present in old spec')
        env.append({'name': FLAG, 'value': '1'})
        metadata = template.setdefault('metadata', {})
        annotations = metadata.setdefault('annotations', {})
        _require(type(annotations) is dict, 'Invalid template annotations')
        annotations[ANNOTATION] = 'read-only-v1'
    except (KeyError, TypeError, AttributeError) as error:
        raise RuntimeError('Required allocator/vllm specification structure differs') from error
    _require(_canonical(new_spec) == _canonical(expected),
             'Candidate spec changed beyond the exact telemetry CM/flag/annotation delta')
    return {
        'proofSHA256': proof_hash,
        'scope': SCOPE,
        'oldObserverSHA256': old_sources[SOURCE],
        'newObserverSHA256': new_sources[SOURCE],
        'allOtherModelSourcesAndNumericalProfileExact': True,
    }
