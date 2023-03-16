import os
import re
from typing import Any, Dict, List, Tuple

from box import Box
from chaoslib.types import Secrets

from chaosgarden.k8s.api.authenticators import (Authenticator,
                                                ConfigAsDictAuthenticator,
                                                ConfigAsFileAuthenticator,
                                                ConfigAsYamlAuthenticator)
from chaosgarden.k8s.api.cluster import API, Cluster


class SelectorRequirement():
    def __init__(self, requirement: str):
        matches = re.match(r'([^!=~]+)(=|==|!=|=~|!~)([^!=~]+)', requirement)
        if matches:
            self.key = matches.group(1).strip()
            self.op  = re.sub(r'^=$', '==', matches.group(2))
            self.val = matches.group(3).strip()
        else:
            raise ValueError(f'Selector requirement "{requirement}" invalid!')

    def __repr__(self):
        return f'{self.key} {self.op} {self.val}'

    def matches(self, labels: Dict[str, str]) -> bool:
        default = False if self.op.startswith('=') else True if self.op.startswith('!') else None
        for key, val in labels.items():
            if self.key == key:
                if self.op == '==':
                    if self.val == val:
                        return True
                if self.op == '!=':
                    if self.val == val:
                        return False
                if self.op == '=~':
                    if re.match(f'^{self.val}', val):
                        return True
                if self.op == '!~':
                    if re.match(f'^{self.val}', val):
                        return False
        return default

    @staticmethod
    def matches_selector(selector: List, entity: Any, labels: Dict[str, str]) -> bool:
        matches = True
        if selector:
            for r in selector:
                matches &= r.matches(labels)
        return matches

    @staticmethod
    def filter_by_selector(selector: List, entity_to_labels: List[Tuple[Any, Dict[str, str]]]) -> List[Any]:
        result = []
        for (entity, labels) in entity_to_labels:
            if SelectorRequirement.matches_selector(selector, entity, labels):
                result.append(entity)
        return result


def supplement_selector(supplement: str, selector: str) -> str:
    if selector:
        return f'{selector},{supplement}'
    else:
        return supplement


def filter_pods(
        cluster: Cluster,
        nodes: List[Dict],
        pod_node_label_selector: List = None,
        pod_label_selector: str = None,
        pod_metadata_selector: List = None,
        pod_owner_selector: List = None) -> List[str]:
    # fetch pods either for one namespace (performance optimization) or for all namespaces
    namespaces = []
    for r in pod_metadata_selector:
        if r.key == 'namespace' and r.op == '==':
            namespaces.append(r.val)
    if len(namespaces) == 1:
        pods = cluster.client(API.CoreV1).list_namespaced_pod(namespaces[0], label_selector = pod_label_selector, _request_timeout = 60)
    else:
        pods = cluster.client(API.CoreV1).list_pod_for_all_namespaces(label_selector = pod_label_selector, _request_timeout = 60)
    pods = cluster.boxed(cluster.sanitize_result(cluster.convert_snakecase_to_camelcase_dict_keys(pods.to_dict())))

    # filter pods by pod metadata and owner selector
    pods = SelectorRequirement.filter_by_selector(pod_metadata_selector, [(pod, pod.metadata) for pod in pods])
    pods = SelectorRequirement.filter_by_selector(pod_owner_selector, [(pod, pod.metadata.ownerReferences[0]) for pod in pods if 'ownerReferences' in pod.metadata and pod.metadata.ownerReferences])

    # filter pods by node label selector
    node_names = {node.metadata.name: node for node in nodes} if nodes else []
    for pod in pods:
        if 'nodeName' in pod.spec and pod.spec.nodeName not in node_names:
            nodes.clear() # preserve list as we keep updating it on every refresh that becomes necessary
            nodes.extend(cluster.boxed(cluster.sanitize_result(cluster.convert_snakecase_to_camelcase_dict_keys(cluster.client(API.CoreV1).list_node(_request_timeout = 15).to_dict()))))
            node_names = {node.metadata.name: node for node in nodes}
        if 'nodeName' in pod.spec and pod.spec.nodeName in node_names:
            for key, value in node_names[pod.spec.nodeName].metadata.labels.items():
                if key in ['topology.kubernetes.io/zone']: # copy useful node labels to pod metadata for convenience
                    if not 'labels' in pod.metadata:
                        pod.metadata['labels'] = Box()
                    pod.metadata['labels'][key] = value
    pods = SelectorRequirement.filter_by_selector(pod_node_label_selector, [(pod, node_names[pod.spec.nodeName].metadata.labels) for pod in pods if 'nodeName' in pod.spec and pod.spec.nodeName in node_names])

    # return filtered pods
    return pods


def filter_leases(
        cluster: Cluster,
        lease_label_selector: str = None,
        lease_metadata_selector: List = None) -> List[str]:
    # fetch leases either for one namespace (performance optimization) or for all namespaces
    namespaces = []
    for r in lease_metadata_selector:
        if r.key == 'namespace' and r.op == '==':
            namespaces.append(r.val)
    if len(namespaces) == 1:
        leases = cluster.client(API.CoordinationV1).list_namespaced_lease(namespaces[0], label_selector = lease_label_selector, _request_timeout = 60)
    else:
        leases = cluster.client(API.CoordinationV1).list_lease_for_all_namespaces(label_selector = lease_label_selector, _request_timeout = 60)
    leases = cluster.boxed(cluster.sanitize_result(cluster.convert_snakecase_to_camelcase_dict_keys(leases.to_dict())))

    # filter leases by lease metadata
    leases = SelectorRequirement.filter_by_selector(lease_metadata_selector, [(lease, lease.metadata) for lease in leases])

    # return filtered leases
    return leases


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
