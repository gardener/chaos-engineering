import os

from box import Box
from chaoslib.types import Secrets

from chaosgarden.k8s.api.authenticators import (Authenticator,
                                                ConfigAsDictAuthenticator,
                                                ConfigAsFileAuthenticator,
                                                ConfigAsYamlAuthenticator)


def to_authenticator(secrets: Secrets = None) -> Authenticator:
    authenticator = None
    if secrets:
        secrets = Box(secrets)
        if 'kubeconfig_struct' in secrets: # not documented because unsafe if specified in experiment file; not used in `chaosgarden`
            authenticator = ConfigAsDictAuthenticator(secrets.kubeconfig_struct)
        elif 'kubeconfig_yaml' in secrets: # not documented because unsafe if specified in experiment file; used in-memory only by `garden` module
            authenticator = ConfigAsYamlAuthenticator(secrets.kubeconfig_yaml)
        elif 'kubeconfig_path' in secrets:
            authenticator = ConfigAsFileAuthenticator(secrets.kubeconfig_path)
    if not authenticator and 'KUBECONFIG' in os.environ:
        authenticator = ConfigAsFileAuthenticator(os.getenv('KUBECONFIG'))
    return authenticator
