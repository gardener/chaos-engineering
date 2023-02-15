import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from threading import Thread
from typing import Dict, List

import yaml
from box import Box
from chaoslib.types import Secrets
from kubernetes.client.exceptions import ApiException
from logzero import logger

from chaosgarden.k8s import to_authenticator
from chaosgarden.k8s.model.cluster import API, Cluster
from chaosgarden.util.terminator import Terminator
from chaosgarden.util.threading import launch_thread

ZONE_UNDER_TEST = 'zone-under-test'


__all__ = [
    'run_cluster_health_probe_in_background',
    'run_cluster_health_probe',
    'rollback_cluster_health_probe']


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

    # generate probe report
    stop_timestamp = int(datetime.now(tz = timezone.utc).timestamp())
    report = generate_report(cluster, thresholds, start_timestamp, stop_timestamp, successful_api_probe_heartbeats, failed_api_probe_heartbeats)

    # rollback
    rollback_cluster_health_probe(secrets)

    # dump and assess probe report
    dump_report(report)
    try:
        assess_report(report)
    except AssertionError as e:
        if silent:
            logger.error(f'Assertion failed: {e}')
            return False
        else:
            raise e
    except Exception as e:
        raise e
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

def setup(cluster: Cluster):
    # TODO handle kubernetes.client.exceptions.ApiException gracefully which may happen if cleanup was called before and the resources are still in deletion:
    # HTTP response headers: HTTPHeaderDict({'Audit-Id': '6b71dfab-e7f3-4e33-892b-1428f8e55522', 'Cache-Control': 'no-cache, private', 'Content-Type': 'application/json', 'X-Kubernetes-Pf-Flowschema-Uid': 'f93f1ed7-bc58-4e57-bcac-4112485cca25', 'X-Kubernetes-Pf-Prioritylevel-Uid': '0fe5f2e7-3c0c-4976-b8f5-c6c0f9ea9d83', 'Date': 'Thu, 09 Feb 2023 13:22:50 GMT', 'Content-Length': '432'})
    # HTTP response body: {"kind":"Status","apiVersion":"v1","metadata":{},"status":"Failure","message":"serviceaccounts \"probe\" is forbidden: unable to create new content in namespace chaos-garden-probe because it is being terminated","reason":"Forbidden","details":{"name":"probe","kind":"serviceaccounts","causes":[{"reason":"NamespaceTerminating","message":"namespace chaos-garden-probe is being terminated","field":"metadata.namespace"}]},"code":403}
    zones = set()
    for node in cluster.boxed(cluster.sanitize_result(cluster.client(API.CoreV1).list_node(_request_timeout = 60).to_dict())):
        try:
            zones.add(node['metadata']['labels']['topology.kubernetes.io/zone'])
        except:
            pass
    logger.info('Cluster spread across the following detected zones: ' + ', '.join(sorted(zones)))
    with open(os.path.join('resources', 'resources.yaml'), 'rt') as file:
        resources = yaml.load_all(file, Loader = yaml.FullLoader)
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
                if 'spec' in resource and 'replicas' in resource['spec'] and len(zones) > 1:
                        logger.info(f'Adapting {resource["kind"].lower()} replicas to {len(zones)} (one per zone).')
                        resource['spec']['replicas'] = len(zones) # e.g. deployment, statefulset
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
    with open(os.path.join('resources', 'resources.yaml'), 'rt') as file:
        resources = yaml.load_all(file, Loader = yaml.FullLoader)
        resources = list(resources)
    resources.reverse()
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
            else:
                kind_snake_case = re.sub('([A-Z]+)', r'_\1', resource['kind']).lower()
                if 'namespace' in resource['metadata']:
                    pass # will be deleted with the namespace
                else:
                    getattr(client, 'delete' + kind_snake_case)(
                        name = resource['metadata']['name'],
                        propagation_policy = 'Foreground',
                        _request_timeout = 60)
        except ApiException as e:
            if e.status == 404:
                pass # ignore missing (resource not found), which is to be expected if the cluster is "clean" and setup calls cleanup
            else:
                logger.error(f'Probe cleanup failed: {type(e)}: {e}')
                # logger.error(traceback.format_exc())
                raise e
        except Exception as e:
            logger.error(f'Probe cleanup failed: {type(e)}: {e}')
            # logger.error(traceback.format_exc())
            raise e

def extract_heartbeat_metadata(heartbeat: Dict):
    segments = re.match(r'^(.+)-probe-(.+)-([0-9]+)', heartbeat.metadata.name)
    return segments.group(1), segments.group(2), int(segments.group(3))

def break_down_heartbeats(heartbeats: List[Dict], thresholds: Dict, start_timestamp: datetime, stop_timestamp: datetime):
    metrics = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict())))
    first_ack = False # it takes a while until the endpoint is up, so the first heart beats may not have been acknowledged
    for hb in heartbeats:
        name, zone, timestamp = extract_heartbeat_metadata(hb)
        if hb.kind == 'AcknowledgedHeartbeat':
            first_ack |= hb.ready
            if first_ack:
                metrics[name][zone]['ready'][timestamp] = hb.ready
        else:
            metrics[name][zone]['ready'][timestamp] = hb.ready
    for name in metrics.keys():
        for zone in metrics[name].keys():
            metrics[name][zone]['received'] = len(metrics[name][zone]['ready'])
    for name in sorted(metrics.keys()):
        if name in thresholds and 'gap' in thresholds[name]:
            gap = thresholds[name]['gap']
            initial_gap = thresholds[name]['initial-gap'] if 'initial-gap' in thresholds[name] else gap
            for zone in sorted(metrics[name].keys()):
                timeseries = metrics[name][zone]
                timestamps = sorted(timeseries['ready'].keys())
                if timestamps[0] > start_timestamp + initial_gap:
                    metrics[name][zone]['ready'][start_timestamp + initial_gap] = None
                    timestamps.insert(0, start_timestamp + initial_gap)
                if timestamps[-1] + initial_gap < stop_timestamp:
                    metrics[name][zone]['ready'][stop_timestamp] = None
                    timestamps.append(stop_timestamp)
                last_seen_timestamp = timestamps[0]
                for timestamp in timestamps[1:]:
                    if timestamp > last_seen_timestamp + gap:
                        for i in range(last_seen_timestamp + gap, timestamp, gap):
                            metrics[name][zone]['ready'][i] = None
                    last_seen_timestamp = timestamp
    with open('heartbeats.log', 'wt') as file:
        file.write(f'# Run from {datetime.fromtimestamp(start_timestamp, tz = timezone.utc).strftime("%H:%M:%S")} ({start_timestamp}) to {datetime.fromtimestamp(stop_timestamp, tz = timezone.utc).strftime("%H:%M:%S")} ({stop_timestamp}):\n')
        for name in sorted(metrics.keys()):
            for zone in sorted(metrics[name].keys()):
                timeseries = metrics[name][zone]
                timestamps = sorted(timeseries['ready'].keys())
                for timestamp in timestamps:
                    time = datetime.fromtimestamp(timestamp, tz = timezone.utc).strftime("%H:%M:%S")
                    file.write(f'{name}:{zone}:{time}:' + ('Ready' if metrics[name][zone]['ready'][timestamp] == True else 'NotReady' if metrics[name][zone]['ready'][timestamp] == False else 'NotReady (Gap)') + '\n')
                    metrics[name][zone]['ready'][timestamp] = metrics[name][zone]['ready'][timestamp] if metrics[name][zone]['ready'][timestamp] != None else False
    for name in sorted(metrics.keys()):
        for zone in sorted(metrics[name].keys()):
            timeseries = metrics[name][zone]
            timestamps = sorted(timeseries['ready'].keys())
            timeseries['total'] = len(timestamps)
            timeseries['phases'] = []
            incidents = 0
            downtime = 0
            last_seen_timestamp = timestamps[0]
            last_seen_status = timeseries['ready'][last_seen_timestamp]
            if len(timestamps) >= 2:
                for timestamp in timestamps[1:]:
                    if timeseries['ready'][timestamp] != last_seen_status or timestamp == timestamps[-1]:
                        phase = Box()
                        phase['ready'] = 'Ready' if last_seen_status else 'NotReady'
                        phase['duration'] = timestamp - last_seen_timestamp
                        timeseries['phases'].append(phase)
                        if phase['ready'] == 'NotReady':
                            incidents += 1
                            downtime  += phase['duration']
                        last_seen_timestamp = timestamp
                        last_seen_status = timeseries['ready'][timestamp]
            else:
                phase = Box()
                phase['ready'] = 'Ready' if last_seen_status else 'NotReady'
                phase['duration'] = 0
                timeseries['phases'].append(phase)
                if phase['ready'] == 'NotReady':
                    incidents += 1
                    downtime  += phase['duration']
            timeseries['incidents'] = incidents
            timeseries['downtime'] = downtime
    return metrics

def generate_report(cluster: Cluster, thresholds: Dict, start_timestamp: datetime, stop_timestamp: datetime, successful_api_probe_heartbeats: List[Dict], failed_api_probe_heartbeats: List[Dict]):
    # calculate metrics
    if thresholds == None:
        thresholds = []
    heartbeats = list(failed_api_probe_heartbeats)
    heartbeats.extend(cluster.boxed(cluster.sanitize_result(cluster.client(API.CustomResources).list_cluster_custom_object(group = 'chaos.gardener.cloud', version = 'v1', plural = 'heartbeats', _request_timeout = 60))))
    heartbeats.extend(cluster.boxed(cluster.sanitize_result(cluster.client(API.CustomResources).list_cluster_custom_object(group = 'chaos.gardener.cloud', version = 'v1', plural = 'acknowledgedheartbeats', _request_timeout = 60))))
    metrics = break_down_heartbeats(heartbeats, thresholds, start_timestamp, stop_timestamp)
    metrics['api']['regional']['sent'] = len(successful_api_probe_heartbeats) + len(failed_api_probe_heartbeats)
    return {'metrics': metrics, 'thresholds': thresholds}

def dump_report(report: Dict):
    # dump metrics
    metrics = report['metrics']
    thresholds = report['thresholds']
    logger.debug(f'Metrics as yaml ({len(metrics)}):')
    logger.debug(yaml.dump(json.loads(json.dumps(metrics)), default_flow_style=False, explicit_start=True, indent=2))
    logger.info(f'Metrics as text ({len(metrics)}):')
    for name in sorted(metrics.keys()):
        logger.info(f'- Probe:  {name.upper()}')
        for zone in sorted(metrics[name].keys()):
            is_ignored = ' Ignored (zone was under test)!' if ZONE_UNDER_TEST in thresholds[name] and zone == thresholds[name][ZONE_UNDER_TEST] else ''
            timeseries = metrics[name][zone]
            timeseries = Box(timeseries)
            logger.info(f'  - Zone: {zone.upper()} ({f"{timeseries.sent} heart beats sent, " if "sent" in timeseries else ""}{timeseries.received} heart beats received and {timeseries.total - timeseries.received} gap heart beats inserted with {timeseries.incidents} incidents and {timeseries.downtime}s downtime in total)' + is_ignored)
            phases = timeseries.phases
            for phase in phases:
                logger.info(f'    - {phase.ready:>9} for {phase.duration:>4}s')

def assess_report(report: Dict):
    # assess metrics
    metrics = report['metrics']
    thresholds = report['thresholds']
    api_probe_heartbeats_received = metrics['api']['regional']['received']
    api_probe_heartbeats_sent     = metrics['api']['regional']['sent']
    assert api_probe_heartbeats_received == api_probe_heartbeats_sent, f'Data loss detected: Only {api_probe_heartbeats_received} heart beats received out of {api_probe_heartbeats_sent} sent successfully in total, which means we lost ETCD data!'
    for name in sorted(metrics.keys()):
        for zone in sorted(metrics[name].keys()):
            if not(ZONE_UNDER_TEST in thresholds[name] and zone == thresholds[name][ZONE_UNDER_TEST]):
                timeseries = metrics[name][zone]
                timeseries = Box(timeseries)
                threshold = thresholds[name]['incidents'] if thresholds and name in thresholds and 'incidents' in thresholds[name] else 0
                assert timeseries.incidents <= threshold, f'{name} was failing {timeseries.incidents}x, which is more than the permitted threshold of {threshold}x incidents, which means we missed our goal!'
                threshold = thresholds[name]['downtime'] if thresholds and name in thresholds and 'downtime' in thresholds[name] else 0
                assert timeseries.downtime <= threshold, f'{name} was failing {timeseries.downtime}s, which is more than the permitted threshold of {threshold}s downtime, which means we missed our goal!'
