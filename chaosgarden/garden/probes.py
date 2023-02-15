from threading import Thread
from typing import Dict

from box import Box

from chaosgarden.garden import get_kubeconfig
from chaosgarden.garden.actions import resolve_zone, resolve_zones
from chaosgarden.k8s import to_authenticator
from chaosgarden.k8s.model.cluster import API, Cluster
from chaosgarden.k8s.probes import (ZONE_UNDER_TEST,
                                    rollback_cluster_health_probe,
                                    run_cluster_health_probe)
from chaosgarden.util.threading import launch_thread

__all__ = [
    'run_shoot_cluster_health_probe_in_background',
    'run_shoot_cluster_health_probe',
    'rollback_shoot_cluster_health_probe']


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
    secrets, zones = resolve_secrets_and_zones(
        configuration = configuration,
        secrets = secrets)
    if thresholds:
        for cfg in thresholds.values():
            if ZONE_UNDER_TEST in cfg:
                cfg[ZONE_UNDER_TEST] = resolve_zone(cfg[ZONE_UNDER_TEST], zones)
    return run_cluster_health_probe(
        duration = duration,
        thresholds = thresholds,
        silent = silent,
        secrets = secrets)

def rollback_shoot_cluster_health_probe(
        configuration: Dict = None,
        secrets: Dict = None):
    secrets, _ = resolve_secrets_and_zones(
        configuration = configuration,
        secrets = secrets)
    return rollback_cluster_health_probe(
        secrets = secrets)


###########
# Helpers #
###########

def resolve_secrets_and_zones(configuration, secrets) -> Dict:
    # prep
    configuration = Box(configuration)
    authenticator = to_authenticator(secrets)

    # access garden cluster and retrieve required data
    garden     = Cluster('garden', authenticator)
    project    = Box(garden.client(API.CustomResources).get_cluster_custom_object(name = configuration.garden.project, group = 'core.gardener.cloud', version = 'v1beta1', plural = 'projects'))
    shoot      = Box(garden.client(API.CustomResources).get_namespaced_custom_object(name = configuration.garden.shoot, namespace = project.spec.namespace, group = 'core.gardener.cloud', version = 'v1beta1', plural = 'shoots'))
    kubeconfig = get_kubeconfig(garden_cluster = garden, project_namespace = project.spec.namespace, shoot_name = configuration.garden.shoot)

    # finally return everything we got
    return {'kubeconfig_yaml': kubeconfig}, resolve_zones(shoot.spec)
