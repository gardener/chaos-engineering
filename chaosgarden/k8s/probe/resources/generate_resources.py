import base64
import datetime
import pkgutil
from collections.abc import Sized
from textwrap import indent

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from mako.template import Template


def render(
        zones: Sized = (None,),
        key_size = 2048,
        crt_validity_hours: int = 24):
    # read template and sources
    templated_resources = pkgutil.get_data(__name__, 'templated_resources.yaml')
    probe_pod_source    = pkgutil.get_data(__name__, 'probe_pod.py')
    suicidal_pod_source = pkgutil.get_data(__name__, 'suicidal_pod.py')

    # generate RSA private key
    key = rsa.generate_private_key(
        public_exponent = 65537, # recommended value, see https://cryptography.io/en/latest/hazmat/primitives/asymmetric/rsa/#generation
        key_size = key_size)
    key_pem = key.private_bytes(
        encoding = serialization.Encoding.PEM,
        format = serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm = serialization.NoEncryption())
    key_pem_b64 = base64.b64encode(key_pem).decode('utf-8')

    # generate self-signed X.509 certificate
    crt_common_name = r'probe.chaos-garden-probe.svc' # must match name and namespace of service
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, crt_common_name)
    ])
    crt = x509.CertificateBuilder() \
        .subject_name(subject) \
        .issuer_name(issuer) \
        .public_key(key.public_key()) \
        .serial_number(x509.random_serial_number()) \
        .not_valid_before(datetime.datetime.utcnow()) \
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(hours = crt_validity_hours)) \
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(crt_common_name)]), critical = True) \
        .sign(key, hashes.SHA256())
    crt_pem = crt.public_bytes(serialization.Encoding.PEM)
    crt_pem_b64 = base64.b64encode(crt_pem).decode('utf-8')

    # render template
    template = Template(templated_resources)
    return template.render(
        replicas = max(1, len(zones)),
        key = key_pem_b64,
        crt = crt_pem_b64,
        probe_pod_source = indent(probe_pod_source.decode('utf-8'), '    '),
        suicidal_pod_source = indent(suicidal_pod_source.decode('utf-8'), '    '))
