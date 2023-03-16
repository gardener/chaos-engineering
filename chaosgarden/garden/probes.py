from threading import Thread
from typing import Dict

from box import Box

from chaosgarden.garden import get_kubeconfig
from chaosgarden.garden.actions import resolve_zones
from chaosgarden.k8s import to_authenticator
from chaosgarden.k8s.api.cluster import API, Cluster
from chaosgarden.k8s.probe.thresholds import Thresholds
from chaosgarden.k8s.probes import (list_cluster_key_resources,
                                    rollback_cluster_health_probe,
                                    run_cluster_health_probe)
from chaosgarden.util.threading import launch_thread

__all__ = [
    'list_shoot_cluster_key_resources',
    'run_shoot_cluster_health_probe_in_background',
    'run_shoot_cluster_health_probe',
    'rollback_shoot_cluster_health_probe']


####################################
# Shoot Cluster Key Resources List #
####################################

def list_shoot_cluster_key_resources(
        pod_node_label_selector: str = None,
        pod_label_selector: str = None,
        pod_metadata_selector: str = None,
        pod_owner_selector: str = None,
        lease_label_selector: str = None,
        lease_metadata_selector: str = None,
        configuration: Dict = None,
        secrets: Dict = None):
    secrets, _ = resolve_secrets_and_spec(
        configuration = configuration,
        secrets = secrets)
    return list_cluster_key_resources(
        pod_node_label_selector = pod_node_label_selector,
        pod_label_selector = pod_label_selector,
        pod_metadata_selector = pod_metadata_selector,
        pod_owner_selector = pod_owner_selector,
        lease_label_selector = lease_label_selector,
        lease_metadata_selector = lease_metadata_selector,
        secrets = secrets)


##############################
# Shoot Cluster Health Probe #
##############################

def run_shoot_cluster_health_probe_in_background(
        duration: int = 0,
        thresholds: Dict = None,
        configuration: Dict = None,
        secrets: Dict = None) -> Thread:
    return launch_thread(target = run_shoot_cluster_health_probe, kwargs = locals())

def run_shoot_cluster_health_probe(
        duration: int = 0,
        thresholds: Dict = None,
        silent: bool = False,
        configuration: Dict = None,
        secrets: Dict = None):
    secrets, spec = resolve_secrets_and_spec(
        configuration = configuration,
        secrets = secrets)
    technical_zones = resolve_zones(spec)
    kubernetes_zones = set()
    for zone in technical_zones:
        # substitute technical numbered zone with Kubernetes named zone that will be used as label at nodes (e.g. Azure)
        kubernetes_zones.add(f'{spec.region}-{zone}' if zone.isnumeric() else zone)
    thresholds = Thresholds.from_dict(thresholds).substitute_zones(dict(enumerate(sorted(kubernetes_zones)))).to_dict()
    return run_cluster_health_probe(
        duration = duration,
        thresholds = thresholds,
        silent = silent,
        secrets = secrets)

def rollback_shoot_cluster_health_probe(
        configuration: Dict = None,
        secrets: Dict = None):
    secrets, _ = resolve_secrets_and_spec(
        configuration = configuration,
        secrets = secrets)
    return rollback_cluster_health_probe(
        secrets = secrets)


###########
# Helpers #
###########

def resolve_secrets_and_spec(configuration, secrets) -> Dict:
    # prep
    configuration = Box(configuration)
    authenticator = to_authenticator(secrets)

    # access garden cluster and retrieve required data
    garden     = Cluster('garden', authenticator)
    project    = Box(garden.client(API.CustomResources).get_cluster_custom_object(name = configuration.garden_project, group = 'core.gardener.cloud', version = 'v1beta1', plural = 'projects'))
    shoot      = Box(garden.client(API.CustomResources).get_namespaced_custom_object(name = configuration.garden_shoot, namespace = project.spec.namespace, group = 'core.gardener.cloud', version = 'v1beta1', plural = 'shoots'))
    kubeconfig = get_kubeconfig(garden_cluster = garden, project_namespace = project.spec.namespace, shoot_name = configuration.garden_shoot)

    # finally return everything we got
    return {'kubeconfig_yaml': kubeconfig}, shoot.spec
