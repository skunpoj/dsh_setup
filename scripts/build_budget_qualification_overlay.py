"""Build an origin-fenced, private qualification overlay without cluster access.

Production sources are inputs, never edited. Generated output contains the
operator's site configuration and must stay outside the public repository.
"""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit

ANCHOR = "    timing.record.update(requestId=rid, inputTokens=tokenized['count'], outputBudget=data['max_tokens'], long=long)"
GATE = """
    print(json.dumps({'event':'qualification_output_reservation','inputTokens':tokenized['count'],'outputBudget':data['max_tokens'],'source':'corrected-private-fixture'}),flush=True)
    if tokenized['count'] >= 950000 and data['max_tokens'] < 512:
        raise HTTPException(422, 'Qualification output reservation failed before preparation; no model call.')
"""


def digest(source):
    return hashlib.sha256(source.encode()).hexdigest()


def origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path or parsed.query or parsed.fragment
            or any(c in value for c in "*'\"\\<>")
            or any(c.isspace() for c in value)):
        raise ValueError('Supply an exact plain HTTP(S) origin without a path or credentials')
    port = parsed.port  # Reject malformed ports before producing any output.
    host = parsed.hostname
    if '%' in host:
        raise ValueError('Use an unescaped canonical hostname without a zone identifier')
    try:
        address = ipaddress.ip_address(host)
        host = '[' + address.compressed + ']' if address.version == 6 else str(address)
    except ValueError:
        if host.rsplit('.', 1)[-1].isdigit() or host.lower().startswith('0x'):
            raise ValueError('Use a canonical IP address, not a numeric URL shorthand')
        host = host.encode('idna').decode('ascii').lower()
    authority = host
    if port is not None and port != {'http': 80, 'https': 443}[parsed.scheme]:
        authority += ':' + str(port)
    if value != parsed.scheme + '://' + authority:
        raise ValueError('Use the exact canonical URL.origin, with default ports omitted')
    return value


def build(transport, forwarder, transport_sha, forwarder_sha,
          canonical_origin, test_origin):
    canonical_origin, test_origin = origin(canonical_origin), origin(test_origin)
    if canonical_origin == test_origin:
        raise ValueError('Qualification requires a separate private test origin')
    if digest(transport) != transport_sha or digest(forwarder) != forwarder_sha:
        raise ValueError('Source fingerprint changed; review before generating an overlay')
    fence = "if (origin !== '" + canonical_origin + "') return;"
    if transport.count(fence) != 1 or forwarder.count(ANCHOR) != 1:
        raise ValueError('Expected single origin fence and forwarding boundary were not found')
    if 'qualification_output_reservation' in forwarder:
        raise ValueError('Qualification gate already present')
    patched = transport.replace(fence, 'if (origin !== ' + json.dumps(test_origin) + ') return;')
    guarded = forwarder.replace(ANCHOR, ANCHOR + GATE)
    return {
        'purpose': 'Private test-route qualification; not a production overlay',
        'productionSourcesUnchanged': True,
        'inputSHA256': {'transport': transport_sha, 'forwarder': forwarder_sha},
        'outputSHA256': {'transport': digest(patched), 'forwarder': digest(guarded)},
        'transportSource': patched,
        'forwarderSource': guarded,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transport-source', type=Path, required=True)
    parser.add_argument('--forwarder-source', type=Path, required=True)
    parser.add_argument('--transport-sha256', required=True)
    parser.add_argument('--forwarder-sha256', required=True)
    parser.add_argument('--canonical-origin', required=True)
    parser.add_argument('--test-origin', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build(args.transport_source.read_bytes().decode('utf-8'),
                   args.forwarder_source.read_bytes().decode('utf-8'),
                   args.transport_sha256, args.forwarder_sha256,
                   args.canonical_origin, args.test_origin)
    args.output.mkdir(exist_ok=False)
    (args.output / 'canary-overlay.json').write_text(
        json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print('Generated private qualification overlay; no cluster changes were made.')


if __name__ == '__main__':
    main()
