import json
import logging
import warnings
from enum import Enum
from threading import RLock

import yaml
from kubernetes.client import (AdmissionregistrationV1Api, ApiextensionsV1Api,
                               AppsV1Api, CoordinationV1Api, CoreV1Api,
                               CustomObjectsApi, EventsV1Api, NetworkingV1Api,
                               PolicyV1Api, RbacAuthorizationV1Api, VersionApi)
from kubernetes.client.exceptions import ApiException
from kubernetes.client.models.events_v1_event import EventsV1Event


# patch EventsV1Event class
def event_time(self, event_time):
  self._event_time = event_time
EventsV1Event.event_time = EventsV1Event.event_time.setter(event_time)

# drop self-signed cert warning
warnings.filterwarnings('ignore', 'Unverified HTTPS request is being made.*') # filter


class API(Enum):
  Raw                     = 'raw'
  Plain                   = 'plain'
  Version                 = 'version'
  CoreV1                  = 'v1'                              # must match real API version
  AppsV1                  = 'apps/v1'                         # "
  PolicyV1                = 'policy/v1'                       # "
  NetworkingV1            = 'networking.k8s.io/v1'            # "
  RbacAuthorizationV1     = 'rbac.authorization.k8s.io/v1'    # "
  AdmissionRegistrationV1 = 'admissionregistration.k8s.io/v1' # "
  CoordinationV1          = 'coordination.k8s.io/v1'          # "
  EventsV1                = 'events.k8s.io/v1'                # "
  ExtensionsV1            = 'apiextensions.k8s.io/v1'         # "
  CustomResources         = 'custom'                          # default for unknown API versions

  @staticmethod
  def from_api_version(api_version):
    try:
      return API(api_version)
    except ValueError:
      return API.CustomResources

  def client(self, raw_client):
    if not raw_client:
      raise ValueError(f'No raw client!')
    if self == self.Raw:
      return raw_client
    elif self == self.Plain:
      return PlainClient(raw_client)
    elif self == self.Version:
      return VersionApi(raw_client)
    elif self == self.CoreV1:
      return CoreV1Api(raw_client)
    elif self == self.AppsV1:
      return AppsV1Api(raw_client)
    elif self == self.PolicyV1:
      return PolicyV1Api(raw_client)
    elif self == self.NetworkingV1:
      return NetworkingV1Api(raw_client)
    elif self == self.RbacAuthorizationV1:
      return RbacAuthorizationV1Api(raw_client)
    elif self == self.AdmissionRegistrationV1:
      return AdmissionregistrationV1Api(raw_client)
    elif self == self.CoordinationV1:
      return CoordinationV1Api(raw_client)
    elif self == self.EventsV1:
      return EventsV1Api(raw_client)
    elif self == self.ExtensionsV1:
      return ApiextensionsV1Api(raw_client)
    elif self == self.CustomResources:
      return CustomObjectsApi(raw_client)
    else:
      raise ValueError(f'Unknown API {self.value}!')


class PlainClient():
  def __init__(self, client):
    self._logger = logging.getLogger(self.__class__.__name__)
    self._client = client

  def get(self, resource_path):
    self._logger.debug('Getting: %s', resource_path)
    try:
      method = 'GET'
      response = self._client.call_api(resource_path          = resource_path,
                                       method                 = method,
                                       auth_settings          = ['BearerToken'],
                                       _preload_content       = False,
                                       _return_http_data_only = True,
                                       _request_timeout       = 60)
      if response.status != 200:
        raise IOError(f'{method} failed with {response.status}!')
    except Exception as exc:
      # self._logger.error(exc, exc_info = True)
      raise exc
    if response.data is None:
      return None
    else:
      if response.headers['Content-Type'].startswith('application/json'):
        return json.loads(response.data)
      elif response.headers['Content-Type'].startswith('application/yaml'):
        return yaml.load(response.data, Loader = yaml.FullLoader)
      else:
        return response.data

  def post(self, resource_path, body):
    self._logger.debug('Posting: %s', resource_path)
    try:
      method = 'POST'
      response = self._client.call_api(resource_path          = resource_path,
                                       method                 = method,
                                       header_params          = {'Content-Type': 'application/yaml'},
                                       body                   = body,
                                       auth_settings          = ['BearerToken'],
                                       _preload_content       = False,
                                       _return_http_data_only = True,
                                       _request_timeout       = 60)
      if response.status != 201:
        raise IOError(f'{method} failed with {response.status}!')
    except Exception as exc:
      # self._logger.error(exc, exc_info = True)
      raise exc
    if response.data is None:
      return None
    else:
      if response.headers['Content-Type'].startswith('application/json'):
        return json.loads(response.data)
      elif response.headers['Content-Type'].startswith('application/yaml'):
        return yaml.load(response.data, Loader = yaml.FullLoader)
      else:
        return response.data


class WrappedRawClient():
  def __init__(self, authenticator):
    self._authenticator = authenticator
    self._lock = RLock()
    self._raw_client = None
    self._api_clients = {}
    self._auth_clients = {}

  def authenticate(self, api, failed_raw_client):
    with self._lock:
      if not self._raw_client or self._raw_client == failed_raw_client:
        # print(f'*' * 100)
        # print(f'* Authenticating via {self._authenticator} for API {api.name}...')
        # print(f'*' * 100)
        self._raw_client = self._authenticator.authenticate()
        self._api_clients = {}
      if api not in self._api_clients:
        self._api_clients[api] = (api.client(self._raw_client), self._raw_client)
    return self._api_clients[api]

  def client(self, api):
    with self._lock:
      if not api in self._auth_clients:
        self._auth_clients[api] = SelfAuthenticatingClient(api, self)
    return self._auth_clients[api]


class SelfAuthenticatingClient():
  def __init__(self, api, wrapped_raw_client):
    self._api = api
    self._wrapped_raw_client = wrapped_raw_client
    self._actual_api_client = self._actual_raw_client = None

  def __getattr__(self, attr_name):
    if not self._actual_api_client:
      self._actual_api_client, self._actual_raw_client = self._wrapped_raw_client.authenticate(self._api, None)
    attr = getattr(self._actual_api_client, attr_name)
    if callable(attr):
      def authenticatable(*args, **kwargs):
        try:
          nonlocal attr
          return attr(*args, **kwargs)
        except ApiException as e:
          if e.status == 401:
            self._actual_api_client, self._actual_raw_client = self._wrapped_raw_client.authenticate(self._api, self._actual_raw_client)
            return getattr(self._actual_api_client, attr_name)(*args, **kwargs)
          else:
            raise
      return authenticatable
    return attr
