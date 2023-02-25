import logging
from socket import AF_INET, SOCK_STREAM, socket

from box import Box

from chaosgarden.k8s.api.clients import API, WrappedRawClient


class Cluster():
  def __init__(self, cluster_name, authenticator):
    self._logger = logging.getLogger(self.__class__.__name__)
    self._cluster_name = cluster_name
    self._client = WrappedRawClient(authenticator)

  @property
  def host(self):
    return self.client().configuration.host

  def client(self, api = API.Raw):
    return self._client.client(api)

  def convert_snakecase_to_camelcase_dict_keys(self, result):
    # results returned by certain API clients have their keys in snakecase, see https://github.com/kubernetes-client/python/issues/1228
    if isinstance(result, dict):
      new_result = {}
      for k, v in result.items():
        k_segments = k.split('_')
        new_result[k_segments[0] + ''.join(segment.title() for segment in k_segments[1:])] = self.convert_snakecase_to_camelcase_dict_keys(v)
    elif isinstance(result, list):
      new_result = []
      for x in result:
        new_result.append(self.convert_snakecase_to_camelcase_dict_keys(x))
    else:
      new_result = result
    return new_result

  def sanitize_result(self, result, default = None):
    if result is None:
      return default
    elif 'kind' in result and result['kind'].endswith('List') and 'items' in result:
      result = result['items']
    if isinstance(result, list):
      items = result
    else:
      items = [result]
    for item in items:
      if item:
        if 'metadata' in item and item['metadata']:
          item['metadata'].pop('managedFields', None)
          if 'annotations' in item['metadata'] and item['metadata']['annotations']:
            item['metadata']['annotations'].pop('kubectl.kubernetes.io/last-applied-configuration', None)
    return result

  def boxed(self, result):
    if result is None:
      return None
    elif 'kind' in result and result['kind'].endswith('List') and 'items' in result:
      result = result['items']
    if isinstance(result, list):
      return [Box(item) for item in result]
    else:
      return Box(result)
