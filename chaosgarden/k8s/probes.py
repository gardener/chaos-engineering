import re
import time
from datetime import datetime, timezone
from threading import Thread
from typing import Dict, List

import yaml
from box import Box
from chaoslib.types import Secrets
from kubernetes.client.exceptions import ApiException
from logzero import logger

from chaosgarden.k8s import (SelectorRequirement, filter_leases, filter_pods,
                             to_authenticator)
from chaosgarden.k8s.api.cluster import API, Cluster
from chaosgarden.k8s.probe.metrics import Metrics
from chaosgarden.k8s.probe.resources.generate_resources import render
from chaosgarden.k8s.probe.thresholds import Thresholds
from chaosgarden.util.terminator import Terminator
from chaosgarden.util.threading import launch_thread

__all__ = [
    'list_cluster_key_resources',
    'run_cluster_health_probe_in_background',
    'run_cluster_health_probe',
    'rollback_cluster_health_probe']


#########################################
# Kubernetes Cluster Key Resources List #
#########################################

def list_cluster_key_resources(
        pod_node_label_selector: str = None,
        pod_label_selector: str = None,
        pod_metadata_selector: str = None,
        pod_owner_selector: str = None,
        lease_label_selector: str = None,
        lease_metadata_selector: str = None,
        configuration: Dict = None,
        secrets: Dict = None):
    # input validation
    pod_node_label_selector = [SelectorRequirement(r) for r in pod_node_label_selector.split(',')] if pod_node_label_selector else []
    pod_label_selector      = pod_label_selector if pod_label_selector else None
    pod_metadata_selector   = [SelectorRequirement(r) for r in pod_metadata_selector.split(',')] if pod_metadata_selector else []
    pod_owner_selector      = [SelectorRequirement(r) for r in pod_owner_selector.split(',')] if pod_owner_selector else []
    lease_label_selector    = lease_label_selector if lease_label_selector else None
    lease_metadata_selector = [SelectorRequirement(r) for r in lease_metadata_selector.split(',')] if lease_metadata_selector else []
    cluster = Cluster(f'cluster', to_authenticator(secrets))

    # dump key resources
    dump_key_resources(cluster, pod_node_label_selector, pod_label_selector, pod_metadata_selector, pod_owner_selector, lease_label_selector, lease_metadata_selector)


###################################
# Kubernetes Cluster Health Probe #
###################################

def run_cluster_health_probe_in_background(
        duration: int = 0,
        thresholds: Dict = None,
        secrets: Secrets = None) -> Thread:
    return launch_thread(target = run_cluster_health_probe, kwargs = locals())

def run_cluster_health_probe(
        duration: int = 0,
        thresholds: Dict = None,
        silent: bool = False,
        secrets: Secrets = None):
    # rollback any left-overs from hard-aborted previous probes
    rollback_cluster_health_probe(secrets)

    # input validation
    cluster = Cluster(f'cluster', to_authenticator(secrets))

    # setup cluster probe
    setup(cluster)
    start_timestamp = int(datetime.now(tz = timezone.utc).timestamp())

    # probe cluster continuously until terminated
    logger.info(f'Probing health of {cluster.host}.')
    successful_api_probe_heartbeats = []
    failed_api_probe_heartbeats = []
    terminator = Terminator(duration)
    while not terminator.is_terminated():
        timestamp = int(datetime.now(tz = timezone.utc).timestamp())
        try:
            hb = {
                'apiVersion': 'chaos.gardener.cloud/v1',
                'kind': 'Heartbeat',
                'metadata': {'name': f'api-probe-regional-{timestamp}'},
                'ready': True
                }
            cluster.client(API.CustomResources).create_cluster_custom_object(body = hb, group = 'chaos.gardener.cloud', version = 'v1', plural = 'heartbeats', _request_timeout = 5)
            successful_api_probe_heartbeats.append(Box(hb))
        except Exception as e:
            logger.error(f'API probe failed: {type(e)}: {e}')
            # logger.error(traceback.format_exc())
            hb['ready'] = False
            failed_api_probe_heartbeats.append(Box(hb))
        finally:
            time.sleep(1)

    # generate metrics
    stop_timestamp = int(datetime.now(tz = timezone.utc).timestamp())
    metrics = generate_metrics(cluster, start_timestamp, stop_timestamp, successful_api_probe_heartbeats, failed_api_probe_heartbeats)

    # rollback
    rollback_cluster_health_probe(secrets)

    # dump and assess metrics
    thresholds = Thresholds.from_dict(thresholds)
    metrics.dump(thresholds)
    violations = metrics.assess(thresholds)
    if violations:
        for v in violations:
            logger.error(v)
        if silent:
            return False
        else:
            raise AssertionError('Probe failed (thresholds violated)!')
    else:
        return True

def rollback_cluster_health_probe(
        secrets: Secrets = None):
    # input validation
    cluster = Cluster(f'cluster', to_authenticator(secrets))

    # cleanup cluster probe
    cleanup(cluster)


###########
# Helpers #
###########

def seconds2human(n):
    units = {
        'y': 365*24*60*60,
        'd': 24*60*60,
        'h': 60*60,
        'm': 60,
        's': 1}
    segments = []
    for unit, quantity in units.items():
        quotient = n // quantity
        if quotient:
            segments.append(f'{quotient}{unit}')
            n -= quotient * quantity
    return ''.join(segments[:2]) if segments else '0s'

def resource_age(resource: Dict):
    return seconds2human(int(datetime.now().timestamp() - resource.metadata.creationTimestamp.timestamp()))

def node_status(node: Dict):
    ready = 'N/A'
    if 'status' in node and 'conditions' in node.status:
        for c in node.status.conditions:
            if c.type == 'Ready':
                ready = 'Ready' if c.status == 'True' else 'NotReady' if c.status == 'False' else c.status
                break
    return ready

def pod_status(pod: Dict):
    phase = 'N/A'
    if 'status' in pod and 'phase' in pod.status:
        phase = pod.status.phase
    ready = 'N/A'
    if 'status' in pod and 'conditions' in pod.status:
        for c in pod.status.conditions:
            if c.type == 'Ready':
                ready = 'Ready' if c.status == 'True' else 'NotReady' if c.status == 'False' else c.status
                break
    return f'{ready} ({phase})'

def dump_key_resources(cluster: Cluster, pod_node_label_selector: List = None, pod_label_selector: str = None, pod_metadata_selector: List = None, pod_owner_selector: List = None, lease_label_selector: str = None, lease_metadata_selector: str = None):
    nodes = []
    pods = filter_pods(
        cluster = cluster,
        nodes = nodes,
        pod_node_label_selector = pod_node_label_selector,
        pod_label_selector = pod_label_selector,
        pod_metadata_selector = pod_metadata_selector,
        pod_owner_selector = pod_owner_selector)
    leases = filter_leases(
        cluster = cluster,
        lease_label_selector = lease_label_selector,
        lease_metadata_selector = lease_metadata_selector)
    logger.debug(f'Nodes:')
    logger.debug(f'  {"NAME":<64} {"STATUS":<21} {"CREATED":<10} ZONE')
    for node in sorted(nodes, key = lambda node: (node.metadata.labels.get('topology.kubernetes.io/zone', 'N/A') if 'labels' in node.metadata else 'N/A', node.metadata.name)):
        logger.debug(f'- {node.metadata.name:<64} {node_status(node):<21} {resource_age(node):<10} {node.metadata.labels.get("topology.kubernetes.io/zone", "N/A") if "labels" in node.metadata else "N/A"}')
    logger.debug(f'Pods:')
    logger.debug(f'  {"NAMESPACE/NAME":<64} {"STATUS":<21} {"CREATED":<10} ZONE (NODE)')
    for pod in sorted(pods, key = lambda pod: (pod.metadata.namespace, pod.metadata.generateName if 'generateName' in pod.metadata else pod.metadata.name, pod.metadata.labels.get('topology.kubernetes.io/zone', 'N/A') if 'labels' in pod.metadata else 'N/A', pod.metadata.name)):
        logger.debug(f'- {pod.metadata.namespace + "/" + pod.metadata.name:<64} {pod_status(pod):<21} {resource_age(pod):<10} {pod.metadata.labels.get("topology.kubernetes.io/zone", "N/A") if "labels" in pod.metadata else "N/A"} ({pod.spec.nodeName if "nodeName" in pod.spec else "N/A"})')
    logger.debug(f'Leases:')
    logger.debug(f'  {"NAMESPACE/NAME":<64} {"ACQUIRED":<10} {"RENEWED":<10} {"CREATED":<10} HOLDER')
    for lease in sorted(leases, key = lambda lease: (lease.metadata.namespace, pod.metadata.name)):
        logger.debug(f'- {lease.metadata.namespace + "/" + lease.metadata.name:<64} {seconds2human(int(datetime.now().timestamp() - lease.spec.acquireTime.timestamp())) if "acquireTime" in lease.spec and lease.spec.acquireTime else "N/A":<10} {seconds2human(int(datetime.now().timestamp() - lease.spec.renewTime.timestamp())) if "renewTime" in lease.spec and lease.spec.renewTime else "N/A":<10} {resource_age(lease):<10} {lease.spec.holderIdentity if "holderIdentity" in lease.spec and lease.spec.holderIdentity else "N/A"}')

def setup(cluster: Cluster):
    zones = set()
    for node in cluster.boxed(cluster.sanitize_result(cluster.client(API.CoreV1).list_node(_request_timeout = 60).to_dict())):
        try:
            zones.add(node['metadata']['labels']['topology.kubernetes.io/zone'])
        except:
            pass
    logger.info('Cluster spread across the following detected zones: ' + ', '.join(sorted(zones)))
    resources = yaml.load_all(render(zones = zones), Loader = yaml.FullLoader)
    resources = list(resources)
    for resource in resources:
        try:
            api_version = resource['apiVersion']
            api = API.from_api_version(api_version)
            client = cluster.client(api)
            if (api == API.CustomResources):
                if 'namespace' in resource['metadata']:
                    client.create_namespaced_custom_object(
                        namespace = resource['metadata']['namespace'],
                        body = resource,
                        group = api_version.split('/')[0],
                        version = api_version.split('/')[1],
                        plural = resource['kind'].lower() + 's', # plural is best guess; proper solution requires reading the CRD first
                        _request_timeout = 60)
                else:
                    client.create_cluster_custom_object(
                        body = resource,
                        group = api_version.split('/')[0],
                        version = api_version.split('/')[1],
                        plural = resource['kind'].lower() + 's', # plural is best guess; proper solution requires reading the CRD first
                        _request_timeout = 60)
            else:
                kind_snake_case = re.sub('([A-Z]+)', r'_\1', resource['kind']).lower()
                if 'namespace' in resource['metadata']:
                    getattr(client, 'create_namespaced' + kind_snake_case)(
                        namespace = resource['metadata']['namespace'],
                        body = resource,
                        _request_timeout = 60)
                else:
                    getattr(client, 'create' + kind_snake_case)(
                        body = resource,
                        _request_timeout = 60)
        except ApiException as e:
            if e.status == 409:
                pass # ignore conflict (resource already found), which is unexpected
            else:
                logger.error(f'Probe setup failed: {type(e)}: {e}')
                # logger.error(traceback.format_exc())
                raise e
        except Exception as e:
            logger.error(f'Probe setup failed: {type(e)}: {e}')
            # logger.error(traceback.format_exc())
            raise e

def cleanup(cluster: Cluster):
    resources = yaml.load_all(render(), Loader = yaml.FullLoader)
    resources = list(resources)
    resources.reverse()
    resources_present = True
    while resources_present:
        resources_present = False
        for resource in resources:
            try:
                api_version = resource['apiVersion']
                api = API.from_api_version(api_version)
                client = cluster.client(api)
                if (api == API.CustomResources):
                    if 'namespace' in resource['metadata']:
                        pass # will be deleted with the namespace
                    else:
                        client.delete_cluster_custom_object(
                            name = resource['metadata']['name'],
                            group = api_version.split('/')[0],
                            version = api_version.split('/')[1],
                            plural = resource['kind'].lower() + 's', # plural is best guess; proper solution requires reading the CRD first
                            propagation_policy = 'Foreground',
                            _request_timeout = 60)
                        resources_present = True
                else:
                    kind_snake_case = re.sub('([A-Z]+)', r'_\1', resource['kind']).lower()
                    if 'namespace' in resource['metadata']:
                        pass # will be deleted with the namespace
                    else:
                        getattr(client, 'delete' + kind_snake_case)(
                            name = resource['metadata']['name'],
                            propagation_policy = 'Foreground',
                            _request_timeout = 60)
                        resources_present = True
            except ApiException as e:
                if e.status == 404:
                    pass # ignore resources that are either missing (cluster was already clean) or were eventually deleted (resource is now gone)
                else:
                    logger.error(f'Probe cleanup failed: {type(e)}: {e}')
                    # logger.error(traceback.format_exc())
                    raise e
            except Exception as e:
                logger.error(f'Probe cleanup failed: {type(e)}: {e}')
                # logger.error(traceback.format_exc())
                raise e
        if resources_present:
            time.sleep(1)

def read_custom_resources(cluster, plural):
    while True:
        try:
            return cluster.boxed(cluster.sanitize_result(cluster.client(API.CustomResources).list_cluster_custom_object(group = 'chaos.gardener.cloud', version = 'v1', plural = plural, _request_timeout = 60)))
        except ApiException as e:
            logger.error(f'Reading custom resources failed: {type(e)}: {e}')
            # logger.error(traceback.format_exc())
            time.sleep(5)
        except Exception as e:
            logger.error(f'Reading custom resources failed: {type(e)}: {e}')
            # logger.error(traceback.format_exc())
            raise e

def generate_metrics(cluster: Cluster, start_timestamp: datetime, stop_timestamp: datetime, successful_api_probe_heartbeats: List[Dict], failed_api_probe_heartbeats: List[Dict]):
    # put together heartbeats
    heartbeats = list(failed_api_probe_heartbeats)                              # heartbeats that failed to reach the API server, but we know of (what was sent successfully will be collected with the next line)
    heartbeats.extend(read_custom_resources(cluster, 'heartbeats'))             # heartbeats that were sent by any probe, here or cluster-internally (we see only what successfully made it to the API server from within the cluster)
    heartbeats.extend(read_custom_resources(cluster, 'acknowledgedheartbeats')) # heartbeats that were acknowledged by the cluster-internal web hook (we see only what successfully made it to the API server from within the cluster)
    if not heartbeats:
        raise AssertionError('Probe errored (no heartbeats or insufficient runtime)!')
    metrics = Metrics(heartbeats, start_timestamp, stop_timestamp)

    # set sent counter for the API heartbeats that were sent from within this file (only for those we know how many were successfully and unsuccessfully sent)
    metrics.get_metrics_for_probe('api').get_metrics_for_zone('regional').record_heartbeats_sent(len(successful_api_probe_heartbeats) + len(failed_api_probe_heartbeats))

    # return the aggregated metrics object
    return metrics
