"""Generate ephemeral localhost-only TLS fixtures; never ship a private key in Git."""
import datetime,ipaddress,sys
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
p=Path(sys.argv[1]);p.mkdir(mode=0o700,exist_ok=False)
key=rsa.generate_private_key(public_exponent=65537,key_size=2048);now=datetime.datetime.now(datetime.timezone.utc)
name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost test fixture')])
cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),False).sign(key,hashes.SHA256()))
(p/'key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));(p/'cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
