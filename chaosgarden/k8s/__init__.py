import os

from box import Box
from chaoslib.types import Secrets

from chaosgarden.k8s.model.cluster_authenticators import (
    Authenticator, ConfigAsDictAuthenticator, ConfigAsFileAuthenticator,
    ConfigAsYamlAuthenticator)


def to_authenticator(secrets: Secrets = None) -> Authenticator:
    authenticator = None
    if secrets:
        secrets = Box(secrets)
        if 'kubeconfig_struct' in secrets:
            authenticator = ConfigAsDictAuthenticator(secrets.kubeconfig_struct)
        elif 'kubeconfig_yaml' in secrets:
            authenticator = ConfigAsYamlAuthenticator(secrets.kubeconfig_yaml)
        elif 'kubeconfig_file' in secrets:
            authenticator = ConfigAsFileAuthenticator(secrets.kubeconfig_file)
        elif 'kubeconfig_envvar' in secrets:
            authenticator = ConfigAsFileAuthenticator(os.getenv(secrets.kubeconfig_envvar))
    if not authenticator and 'KUBECONFIG' in os.environ:
        authenticator = ConfigAsFileAuthenticator(os.getenv('KUBECONFIG'))
    return authenticator
