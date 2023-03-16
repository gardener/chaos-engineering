import random
import time
from datetime import datetime, timedelta
from threading import Thread

from chaoslib.types import Secrets
from logzero import logger

from chaosgarden.k8s import SelectorRequirement, filter_pods, to_authenticator
from chaosgarden.k8s.api.cluster import API, Cluster
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
        pod_node_label_selector: str = None,
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
        pod_node_label_selector: str = None, # e.g. `topology.kubernetes.io/zone=us-east-1a,worker.gardener.cloud/pool=cpu-worker,...` # right-hand side may be a regex, operators are =|==|!=|=~|!~
        pod_label_selector: str = None,      # e.g. `gardener.cloud/role=controlplane,gardener.cloud/role=vpa,...`                     # regular pod label selector (not interpreted by chaosgarden)
        pod_metadata_selector: str = None,   # e.g. `namespace=kube-system,name=kube-apiserver.*,...`                                  # right-hand side may be a regex, operators are =|==|!=|=~|!~
        pod_owner_selector: str = None,      # e.g. `kind!=DaemonSet,name=kube-apiserver.*,...`                                        # right-hand side may be a regex, operators are =|==|!=|=~|!~
        duration: int = 0,
        secrets: Secrets = None):
    # input validation
    max_runtime = max(min_runtime, max_runtime)
    pod_node_label_selector = [SelectorRequirement(r) for r in pod_node_label_selector.split(',')] if pod_node_label_selector else []
    pod_label_selector      = pod_label_selector if pod_label_selector else None
    pod_metadata_selector   = [SelectorRequirement(r) for r in pod_metadata_selector.split(',')] if pod_metadata_selector else []
    pod_owner_selector      = [SelectorRequirement(r) for r in pod_owner_selector.split(',')] if pod_owner_selector else []
    cluster = Cluster(f'cluster', to_authenticator(secrets))

    # mess up pods continuously until terminated
    logger.info(f'Terminating pods in {cluster.host} matching {pod_node_label_selector=}, {pod_label_selector=}, {pod_metadata_selector=}, {pod_owner_selector=} with runtime between {min_runtime}s and {max_runtime}s with a grace period of {grace_period}s.')
    nodes = []
    schedule_by_id = {}
    terminator = Terminator(duration)
    while not terminator.is_terminated():
        try:
            pods = filter_pods(
                cluster = cluster,
                nodes = nodes,
                pod_node_label_selector = pod_node_label_selector,
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
