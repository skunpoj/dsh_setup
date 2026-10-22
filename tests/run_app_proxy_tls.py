"""Run a synthetic HTTPS/WebSocket fixture against the actual gateway scripts.

No cluster, model request, real account or global DNS/TLS setting is used.
Certificates and synthetic state live in a temporary directory only.
"""
import argparse
import datetime
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile


def certificate(folder, hostname):
    openssl = os.environ.get('OPENSSL_BIN') or shutil.which('openssl')
    cert, key = folder / 'fixture-ca.pem', folder / 'fixture-key.pem'
    if openssl:
        subprocess.run([openssl, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(key), '-out', str(cert), '-days', '2',
                        '-subj', '/CN=' + hostname,
                        '-addext', 'subjectAltName=DNS:' + hostname],
                       check=True, capture_output=True)
        return
    # Optional Windows fallback; the reference Linux image already has OpenSSL.
    from cryptography import x509
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    secret = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.datetime.now(datetime.timezone.utc)
    leaf = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(secret.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=2))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), False)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
            .sign(secret, hashes.SHA256()))
    cert.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key.write_bytes(secret.private_bytes(serialization.Encoding.PEM,
                                         serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', default='node')
    parser.add_argument('--previous-source', type=Path,
                        help='Optional trusted previous scripts directory for code-only recovery')
    args = parser.parse_args()
    addresses = {v[4][0] for v in socket.getaddrinfo(socket.gethostname(), None,
                                                    socket.AF_INET, socket.SOCK_STREAM)}
    addresses = sorted(x for x in addresses if ipaddress.ip_address(x).is_private
                       and not ipaddress.ip_address(x).is_loopback
                       and not ipaddress.ip_address(x).is_link_local)
    if not addresses:
        raise RuntimeError('A local private IPv4 interface is required; use a bridged test container')
    address = addresses[0]
    # Fail before starting the fixture if the selected address is not locally owned.
    with socket.socket() as probe:
        probe.bind((address, 0))
    hostname = 'fixture.example.test'
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='dsh-proxy-tls-') as temporary:
        folder = Path(temporary)
        certificate(folder, hostname)
        # Controlled DNS exists only inside the synthetic gateway child process.
        preload = (
            "const dns=require('node:dns');const original=dns.promises.lookup.bind(dns.promises);"
            "dns.promises.lookup=async(host,opts)=>host===" + json.dumps(hostname)
            + "?[{address:" + json.dumps(address) + ",family:4}]:original(host,opts);\n"
        )
        (folder / 'dns.cjs').write_text(preload, encoding='utf-8')
        env = {**os.environ, 'EXTERNAL_FIXTURE_HOST': hostname,
               'EXTERNAL_FIXTURE_IP': address, 'DSH_PROXY_FIXTURE_DIR': str(folder)}
        env.pop('DSH_PREVIOUS_GATEWAY_SOURCE', None)
        if args.previous_source:
            previous = args.previous_source.resolve(strict=True)
            if not (previous / 'auth_proxy.js').is_file():
                raise ValueError('Previous source must contain the trusted gateway and its helpers')
            env['DSH_PREVIOUS_GATEWAY_SOURCE'] = str(previous)
        result = subprocess.run([args.node, str(root / 'tests/app_proxy/test_proxy_compatibility.cjs')],
                                cwd=root, env=env, capture_output=True, timeout=90)
        print(result.stdout.decode('utf-8', errors='replace'))
        if result.returncode:
            print(result.stderr.decode('utf-8', errors='replace'))
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
