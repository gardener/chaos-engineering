import random
import re
import time
from datetime import datetime, timedelta
from threading import Thread
from typing import Any, Dict, List, Tuple

from chaoslib.types import Secrets
from logzero import logger

from chaosgarden.k8s import to_authenticator
from chaosgarden.k8s.model.cluster import API, Cluster
from chaosgarden.util.terminator import Terminator
from chaosgarden.util.threading import launch_thread

__all__ = [
    'run_pod_failure_simulation_in_background',
    'run_pod_failure_simulation']


#####################################
# Kubernetes Pod Failure Simulation #
#####################################

def run_pod_failure_simulation_in_background(
        min_runtime: int = 0,
        max_runtime: int = 0,
        grace_period: int = 0,
        node_label_selector: str = None,
        pod_label_selector: str = None,
        pod_metadata_selector: str = None,
        pod_owner_selector: str = None,
        duration: int = 0,
        secrets: Secrets = None) -> Thread:
    return launch_thread(target = run_pod_failure_simulation, kwargs = locals())

def run_pod_failure_simulation(
        min_runtime: int = 0,
        max_runtime: int = 0,
        grace_period: int = 0,
        node_label_selector: str = None,   # e.g. `topology.kubernetes.io/zone=us-east-1a,worker.gardener.cloud/pool=cpu-worker,...` # right-hand side may be a regex, operators are =|==|!=|=~|!~
        pod_label_selector: str = None,    # e.g. `gardener.cloud/role=controlplane,gardener.cloud/role=vpa,...`                     # regular pod label selector (not interpreted by chaosgarden)
        pod_metadata_selector: str = None, # e.g. `namespace=kube-system,name=kube-apiserver.*,...`                                  # right-hand side may be a regex, operators are =|==|!=|=~|!~
        pod_owner_selector: str = None,    # e.g. `kind!=DaemonSet,name=kube-apiserver.*,...`                                        # right-hand side may be a regex, operators are =|==|!=|=~|!~
        duration: int = 0,
        secrets: Secrets = None):
    # input validation
    max_runtime = max(min_runtime, max_runtime)
    node_label_selector   = [SelectorRequirement(r) for r in node_label_selector.split(',')] if node_label_selector else []
    pod_label_selector    = pod_label_selector if pod_label_selector else None
    pod_metadata_selector = [SelectorRequirement(r) for r in pod_metadata_selector.split(',')] if pod_metadata_selector else []
    pod_owner_selector    = [SelectorRequirement(r) for r in pod_owner_selector.split(',')] if pod_owner_selector else []
    cluster = Cluster(f'cluster', to_authenticator(secrets))

    # mess up pods continuously until terminated
    logger.info(f'Terminating pods in {cluster.host} matching {node_label_selector=}, {pod_label_selector=}, {pod_metadata_selector=}, {pod_owner_selector=} with runtime between {min_runtime}s and {max_runtime}s with a grace period of {grace_period}s.')
    nodes = []
    schedule_by_id = {}
    terminator = Terminator(duration)
    while not terminator.is_terminated():
        try:
            pods = filter_pods(
                cluster = cluster,
                nodes = nodes,
                node_label_selector = node_label_selector,
                pod_label_selector = pod_label_selector,
                pod_metadata_selector = pod_metadata_selector,
                pod_owner_selector = pod_owner_selector)
            for pod in pods:
                pod_id = pod.metadata.uid
                if pod_id not in schedule_by_id:
                    schedule_by_id[pod_id] = pod.metadata.creationTimestamp + timedelta(seconds = random.randint(min_runtime, max_runtime))
                    logger.info(f'Scheduling pod termination: {cluster.host}:{pod.metadata.namespace}/{pod.metadata.name} at {schedule_by_id[pod_id]}')
                if datetime.now().astimezone() > schedule_by_id[pod_id]:
                    try:
                        cluster.client(API.CoreV1).delete_namespaced_pod(pod.metadata.name, pod.metadata.namespace, grace_period_seconds = grace_period, _request_timeout = 15)
                        del schedule_by_id[pod_id]
                    except Exception as e:
                        logger.error(f'Pod termination failed for {cluster.host}:{pod.metadata.namespace}/{pod.metadata.name}: {type(e)}: {e}')
                        # logger.error(traceback.format_exc())
                        schedule_by_id[pod_id] = datetime.now().astimezone() + timedelta(seconds = 5) # back-off
        except Exception as e:
            logger.error(f'Pod termination failed: {type(e)}: {e}')
            # logger.error(traceback.format_exc())
        finally:
            time.sleep(1)

###########
# Helpers #
###########

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
    def matches_selector(selector: List, entity: Any, labels: List[str]) -> bool:
        matches = True
        if selector:
            for r in selector:
                matches &= r.matches(labels)
        return matches

    @staticmethod
    def filter_by_selector(selector: List, entity_to_labels: List[Tuple[Any, List[str]]]) -> List[Any]:
        result = []
        for (entity, labels) in entity_to_labels:
            if SelectorRequirement.matches_selector(selector, entity, labels):
                result.append(entity)
        return result

def filter_pods(
        cluster: Cluster,
        nodes: List[Dict],
        node_label_selector: List = None,
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
    if node_label_selector:
        node_names = {node.metadata.name: node for node in nodes} if nodes else []
        for pod in pods:
            if 'nodeName' in pod.spec and pod.spec.nodeName not in node_names:
                nodes.clear() # preserve list as we keep updating it on every refresh that becomes necessary
                nodes.extend(cluster.boxed(cluster.sanitize_result(cluster.convert_snakecase_to_camelcase_dict_keys(cluster.client(API.CoreV1).list_node(_request_timeout = 15).to_dict()))))
                node_names = {node.metadata.name: node for node in nodes}
                break
        pods = SelectorRequirement.filter_by_selector(node_label_selector, [(pod, node_names[pod.spec.nodeName].metadata.labels) for pod in pods if 'nodeName' in pod.spec and pod.spec.nodeName in node_names])

    # return filtered pods
    return pods
