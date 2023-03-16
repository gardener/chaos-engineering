import abc
import base64
import logging

import yaml
from kubernetes.client import ApiClient, Configuration
from kubernetes.config import (load_kube_config_from_dict,
                               new_client_from_config)

from chaosgarden.k8s.api.clients import API


class Authenticator():
  __metaclass__  = abc.ABCMeta
  _logger = logging.getLogger(__name__)

  @abc.abstractmethod
  def authenticate(self):
    """Return authenticated Kubernetes client."""


class ConfigAsSecretAuthenticator():
  def __init__(self, cluster, namespace, secret_name):
    self._cluster     = cluster
    self._namespace   = namespace
    self._secret_name = secret_name

  def authenticate(self):
    return ConfigAsSecretResourceAuthenticator(self._cluster.client(API.CoreV1).read_namespaced_secret(name = self._secret_name, namespace = self._namespace, _request_timeout = 15)).authenticate()


class ConfigAsSecretResourceAuthenticator():
  def __init__(self, secret_dict, secret_key ='kubeconfig'):
    self.authenticate = ConfigAsBase64Authenticator(secret_dict.data[secret_key]).authenticate


class ConfigAsSecretDictAuthenticator():
  def __init__(self, secret_dict, secret_key = 'kubeconfig'):
    self.authenticate = ConfigAsBase64Authenticator(secret_dict['data'][secret_key]).authenticate


class ConfigAsBase64Authenticator():
  def __init__(self, text):
    self.authenticate = ConfigAsYamlAuthenticator(base64.b64decode(text).decode('utf-8')).authenticate


class ConfigAsYamlAuthenticator():
  def __init__(self, text):
    self.authenticate = ConfigAsDictAuthenticator(yaml.load(text, Loader = yaml.FullLoader)).authenticate


class ConfigAsDictAuthenticator():
  def __init__(self, dict):
    self._dict = dict

  def authenticate(self):
    for context in self._dict['contexts']:
      if context['name'] == self._dict['current-context']:
        for user in self._dict['users']:
          if user['name'] == context['context']['user']:
            if 'auth-provider' in user['user']:
              raise ValueError('Unsupported auth-provider ' + user['user']['auth-provider']['name'] + '!')
    client_configuration = Configuration()
    load_kube_config_from_dict(config_dict          = self._dict,
                               client_configuration = client_configuration,
                               persist_config       = False,
                               temp_file_path       = None)
    return ApiClient(configuration = client_configuration)


class ConfigAsFileAuthenticator():
  def __init__(self, file_name):
    self._file_name = file_name

  def authenticate(self):
    return new_client_from_config(config_file = self._file_name)


class ConfigAsProjectedTokenAuthenticator():
  def __init__(self, file_name, endpoint_url, ca_cert = None):
    kubeconfig = {
      'apiVersion': 'v1',
      'kind': 'Config',
      'current-context': 'context',
      'contexts': [ { 'name': 'context', 'context': { 'cluster': 'cluster', 'user': 'user' } } ],
      'clusters': [ { 'name': 'cluster', 'cluster': { 'server': endpoint_url } } ],
      'users':    [ { 'name': 'user',    'user':    { 'tokenFile': file_name } } ] }
    if ca_cert:
      kubeconfig['clusters'][0]['cluster']['certificate-authority-data'] = base64.b64encode(ca_cert.encode('utf-8')).decode('utf-8')
    self._authenticator = ConfigAsDictAuthenticator(kubeconfig)

  def authenticate(self):
    return self._authenticator.authenticate()
