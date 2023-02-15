import base64
import inspect
import json
from enum import Enum
from importlib import import_module
from threading import Thread
from typing import Any, Callable, Dict, List, Set, Tuple, Union

from box import Box

from chaosgarden.garden import get_kubeconfig
from chaosgarden.k8s import to_authenticator
from chaosgarden.k8s.actions import run_pod_failure_simulation
from chaosgarden.k8s.model.cluster import API, Cluster
from chaosgarden.util.threading import launch_thread

__all__ = [
    'run_control_plane_pod_failure_simulation_in_background',
    'run_control_plane_pod_failure_simulation',
    'run_system_components_pod_failure_simulation_in_background',
    'run_system_components_pod_failure_simulation',
    'run_general_pod_failure_simulation_in_background',
    'run_general_pod_failure_simulation',
    'assess_cloud_provider_filters_impact',
    'run_cloud_provider_compute_failure_simulation_in_background',
    'run_cloud_provider_compute_failure_simulation',
    'run_cloud_provider_network_failure_simulation_in_background',
    'run_cloud_provider_network_failure_simulation',
    'rollback_cloud_provider_network_failure_simulation']


########################################
# Control Plane Pod Failure Simulation #
########################################

def run_control_plane_pod_failure_simulation_in_background(
        min_runtime: int = 0,
        max_runtime: int = 0,
        grace_period: int = 0,
        zone: Union[int, str] = None,
        node_label_selector: str = None,
        pod_label_selector: str = None,
        pod_metadata_selector: str = None,
        pod_owner_selector: str = None,
        duration: int = 0,
        configuration: Dict = None,
        secrets: Dict = None) -> Thread:
    return launch_thread(target = run_control_plane_pod_failure_simulation, kwargs = locals())

def run_control_plane_pod_failure_simulation(
        min_runtime: int = 0,
        max_runtime: int = 0,
        grace_period: int = 0,
        zone: Union[int, str] = None,
        node_label_selector: str = None,
        pod_label_selector: str = None,
        pod_metadata_selector: str = None,
        pod_owner_selector: str = None,
        duration: int = 0,
        configuration: Dict = None,
        secrets: Dict = None):
    node_label_selector, pod_label_selector, pod_metadata_selector, pod_owner_selector, secrets = resolve_pod_simulation(
        target = Target.ControlPlane,
        zone = zone,
        ignore_daemon_sets = True,
        node_label_selector = node_label_selector,
        pod_label_selector = pod_label_selector,
        pod_metadata_selector = pod_metadata_selector,
        pod_owner_selector = pod_owner_selector,
        configuration = configuration,
        secrets = secrets)
    return run_pod_failure_simulation(
        min_runtime = min_runtime,
        max_runtime = max_runtime,
        grace_period = grace_period,
        node_label_selector = node_label_selector,
        pod_label_selector = pod_label_selector,
        pod_metadata_selector = pod_metadata_selector,
        pod_owner_selector = pod_owner_selector,
        duration = duration,
        secrets = secrets)


############################################
# System Components Pod Failure Simulation #
############################################

def run_system_components_pod_failure_simulation_in_background(
        min_runtime: int = 0,
        max_runtime: int = 0,
        grace_period: int = 0,
        zone: Union[int, str] = None,
        ignore_daemon_sets: bool = False,
        node_label_selector: str = None,
        pod_label_selector: str = None,
        pod_metadata_selector: str = None,
        pod_owner_selector: str = None,
        duration: int = 0,
        configuration: Dict = None,
        secrets: Dict = None) -> Thread:
    return launch_thread(target = run_system_components_pod_failure_simulation, kwargs = locals())

def run_system_components_pod_failure_simulation(
        min_runtime: int = 0,
        max_runtime: int = 0,
        grace_period: int = 0,
        zone: Union[int, str] = None,
        ignore_daemon_sets: bool = False,
        node_label_selector: str = None,
        pod_label_selector: str = None,
        pod_metadata_selector: str = None,
        pod_owner_selector: str = None,
        duration: int = 0,
        configuration: Dict = None,
        secrets: Dict = None):
    node_label_selector, pod_label_selector, pod_metadata_selector, pod_owner_selector, secrets = resolve_pod_simulation(
        target = Target.SystemComponents,
        zone = zone,
        ignore_daemon_sets = ignore_daemon_sets,
        node_label_selector = node_label_selector,
        pod_label_selector = pod_label_selector,
        pod_metadata_selector = pod_metadata_selector,
        pod_owner_selector = pod_owner_selector,
        configuration = configuration,
        secrets = secrets)
    return run_pod_failure_simulation(
        min_runtime = min_runtime,
        max_runtime = max_runtime,
        grace_period = grace_period,
        node_label_selector = node_label_selector,
        pod_label_selector = pod_label_selector,
        pod_metadata_selector = pod_metadata_selector,
        pod_owner_selector = pod_owner_selector,
        duration = duration,
        secrets = secrets)


##################################
# General Pod Failure Simulation #
##################################

def run_general_pod_failure_simulation_in_background(
        min_runtime: int = 0,
        max_runtime: int = 0,
        grace_period: int = 0,
        zone: Union[int, str] = None,
        ignore_daemon_sets: bool = False,
        node_label_selector: str = None,
        pod_label_selector: str = None,
        pod_metadata_selector: str = None,
        pod_owner_selector: str = None,
        duration: int = 0,
        configuration: Dict = None,
        secrets: Dict = None) -> Thread:
    return launch_thread(target = run_general_pod_failure_simulation, kwargs = locals())

def run_general_pod_failure_simulation(
        min_runtime: int = 0,
        max_runtime: int = 0,
        grace_period: int = 0,
        zone: Union[int, str] = None,
        ignore_daemon_sets: bool = False,
        node_label_selector: str = None,
        pod_label_selector: str = None,
        pod_metadata_selector: str = None,
        pod_owner_selector: str = None,
        duration: int = 0,
        configuration: Dict = None,
        secrets: Dict = None):
    node_label_selector, pod_label_selector, pod_metadata_selector, pod_owner_selector, secrets = resolve_pod_simulation(
        target = Target.Workers,
        zone = zone,
        ignore_daemon_sets = ignore_daemon_sets,
        node_label_selector = node_label_selector,
        pod_label_selector = pod_label_selector,
        pod_metadata_selector = pod_metadata_selector,
        pod_owner_selector = pod_owner_selector,
        configuration = configuration,
        secrets = secrets)
    return run_pod_failure_simulation(
        min_runtime = min_runtime,
        max_runtime = max_runtime,
        grace_period = grace_period,
        node_label_selector = node_label_selector,
        pod_label_selector = pod_label_selector,
        pod_metadata_selector = pod_metadata_selector,
        pod_owner_selector = pod_owner_selector,
        duration = duration,
        secrets = secrets)


#################################
# Cloud Provider Filters Impact #
#################################

def assess_cloud_provider_filters_impact(
        zone: Union[int, str] = None,
        configuration: Dict = None,
        secrets: Dict = None):
    simulation, zone, filters, configuration, secrets = resolve_cloud_provider_simulation(
        zone,
        configuration,
        secrets)
    return simulation(
        zone = zone,
        filters = filters,
        configuration = configuration,
        secrets = secrets)


#############################################
# Cloud Provider Compute Failure Simulation #
#############################################

def run_cloud_provider_compute_failure_simulation_in_background(
        mode: str = 'terminate', # modes: 'terminate'|'restart'
        min_runtime: int = 0,
        max_runtime: int = 0,
        zone: Union[int, str] = None,
        duration: int = 0,
        configuration: Dict = None,
        secrets: Dict = None) -> Thread:
    return launch_thread(target = run_cloud_provider_compute_failure_simulation, kwargs = locals())

def run_cloud_provider_compute_failure_simulation(
        mode: str = 'terminate', # modes: 'terminate'|'restart'
        min_runtime: int = 0,
        max_runtime: int = 0,
        zone: Union[int, str] = None,
        duration: int = 0,
        configuration: Dict = None,
        secrets: Dict = None):
    simulation, zone, filters, configuration, secrets = resolve_cloud_provider_simulation(
        zone,
        configuration,
        secrets)
    return simulation(
        mode = mode,
        min_runtime = min_runtime,
        max_runtime = max_runtime,
        zone = zone,
        filters = filters,
        duration = duration,
        configuration = configuration,
        secrets = secrets)


#############################################
# Cloud Provider Network Failure Simulation #
#############################################

def run_cloud_provider_network_failure_simulation_in_background(
        mode: str = 'total', # modes: 'total'|'ingress'|'egress'
        zone: Union[int, str] = None,
        duration: int = 0,
        configuration: Dict = None,
        secrets: Dict = None) -> Thread:
    return launch_thread(target = run_cloud_provider_network_failure_simulation, kwargs = locals())

def run_cloud_provider_network_failure_simulation(
        mode: str = 'total', # modes: 'total'|'ingress'|'egress'
        zone: Union[int, str] = None,
        duration: int = 0,
        configuration: Dict = None,
        secrets: Dict = None):
    simulation, zone, filters, configuration, secrets = resolve_cloud_provider_simulation(
        zone,
        configuration,
        secrets)
    return simulation(
        mode = mode,
        zone = zone,
        filters = filters,
        duration = duration,
        configuration = configuration,
        secrets = secrets)

def rollback_cloud_provider_network_failure_simulation(
        mode: str = 'total', # modes: 'total'|'ingress'|'egress'
        zone: Union[int, str] = None,
        configuration: Dict = None,
        secrets: Dict = None):
    simulation, zone, filters, configuration, secrets = resolve_cloud_provider_simulation(
        zone,
        configuration,
        secrets)
    return simulation(
        mode = mode,
        zone = zone,
        filters = filters,
        configuration = configuration,
        secrets = secrets)


###########
# Helpers #
###########

class Target(Enum):
    ControlPlane      = 'ControlPlane'
    SystemComponents  = 'SystemComponents'
    Workers           = 'Workers'

def resolve_zones(spec: Dict) -> Set:
    zones = set()
    for worker in spec.provider.workers:
        zones |= set(worker.zones)
    return zones

def resolve_zone(zone: Union[int, str], zones: Set) -> str:
    if isinstance(zone, int):
        zones = sorted(zones)
        zones_as_string = ', '.join(zones)
        assert zone >= 0 and zone < len(zones), f'Zone index {zone} out of bounds (known zones are {zones_as_string})!'
        zone = zones[zone]
    else:
        assert zone in zones, f'Zone designator {zone} not recognised (known zones are {zones_as_string})!'
    return zone

def supplement_selector(supplement: str, selector: str) -> str:
    if selector:
        return f'{selector},{supplement}'
    else:
        return supplement

def resolve_pod_simulation(target, zone, ignore_daemon_sets, node_label_selector, pod_label_selector, pod_metadata_selector, pod_owner_selector, configuration, secrets) -> Tuple[str, str, str, str, Dict]:
    # prep
    configuration = Box(configuration)
    authenticator = to_authenticator(secrets)

    # access garden cluster and retrieve required data
    garden  = Cluster('garden', authenticator)
    project = Box(garden.client(API.CustomResources).get_cluster_custom_object(name = configuration.garden.project, group = 'core.gardener.cloud', version = 'v1beta1', plural = 'projects'))
    shoot   = Box(garden.client(API.CustomResources).get_namespaced_custom_object(name = configuration.garden.shoot, namespace = project.spec.namespace, group = 'core.gardener.cloud', version = 'v1beta1', plural = 'shoots'))
    if target == Target.ControlPlane:
        seed = Box(garden.client(API.CustomResources).get_cluster_custom_object(name = shoot.spec.seedName, group = 'core.gardener.cloud', version = 'v1beta1', plural = 'seeds'))
        try:
            seed_shoot = Box(garden.client(API.CustomResources).get_namespaced_custom_object(name = shoot.spec.seedName, namespace = 'garden', group = 'core.gardener.cloud', version = 'v1beta1', plural = 'shoots'))
            kubeconfig = get_kubeconfig(garden_cluster = garden, project_namespace = 'garden', shoot_name = shoot.spec.seedName)
            zone       = resolve_zone(zone, resolve_zones(seed_shoot.spec))
        except:
            kubeconfig = base64.b64decode(garden.client(API.CoreV1).read_namespaced_secret(name = seed.spec.secretRef.name, namespace = seed.spec.secretRef.namespace).data['kubeconfig']).decode('utf-8')
            # zone cannot be resolved/validated, so we do not touch it
    else:
        kubeconfig = get_kubeconfig(garden_cluster = garden, project_namespace = project.spec.namespace, shoot_name = shoot.metadata.name)
        zone       = resolve_zone(zone, resolve_zones(shoot.spec))

    # update selectors
    if zone:
        node_label_selector = supplement_selector(f'topology.kubernetes.io/zone={zone}', node_label_selector)
    if ignore_daemon_sets:
        pod_owner_selector = supplement_selector(f'kind!=DaemonSet', pod_owner_selector)
    if target == Target.ControlPlane:
        pod_label_selector = supplement_selector(f'gardener.cloud/role in (controlplane,vpa)', pod_label_selector)
        pod_metadata_selector = supplement_selector(f'namespace={shoot.status.technicalID}', pod_metadata_selector)
    elif target == Target.SystemComponents:
        pod_label_selector = supplement_selector(f'resources.gardener.cloud/managed-by=gardener', pod_label_selector)
        pod_metadata_selector = supplement_selector(f'namespace=kube-system', pod_metadata_selector)

    # finally return everything we got
    return node_label_selector, pod_label_selector, pod_metadata_selector, pod_owner_selector, {'kubeconfig_yaml': kubeconfig}

def resolve_cloud_provider_simulation(zone, configuration, secrets) -> Tuple[Callable, str, List[Dict[str, Any]], Dict, Dict]:
    # prep
    configuration = Box(configuration)
    authenticator = to_authenticator(secrets)
    simulation = inspect.stack()[1].function

    # access garden cluster and retrieve required data
    garden          = Cluster('garden', authenticator)
    project         = Box(garden.client(API.CustomResources).get_cluster_custom_object(name = configuration.garden.project, group = 'core.gardener.cloud', version = 'v1beta1', plural = 'projects'))
    shoot           = Box(garden.client(API.CustomResources).get_namespaced_custom_object(name = configuration.garden.shoot, namespace = project.spec.namespace, group = 'core.gardener.cloud', version = 'v1beta1', plural = 'shoots'))
    secret_binding  = Box(garden.client(API.CustomResources).get_namespaced_custom_object(name = shoot.spec.secretBindingName, namespace = project.spec.namespace, group = 'core.gardener.cloud', version = 'v1beta1', plural = 'secretbindings'))
    credentials     = Box(garden.client(API.CoreV1).read_namespaced_secret(name = secret_binding.secretRef.name, namespace = secret_binding.secretRef.namespace).data)

    # handle different cloud providers
    cloud_provider = shoot.spec.provider.type
    zone = resolve_zone(zone, resolve_zones(shoot.spec))
    if cloud_provider == 'aws':
        filters = {
            'instances': [{'Name': 'tag-key', 'Values': [f'kubernetes.io/cluster/{shoot.status.technicalID}']}],
            'vpcs': [{'Name': 'tag-key', 'Values': [f'kubernetes.io/cluster/{shoot.status.technicalID}']}]}
        configuration = {
            'aws_region': shoot.spec.region}
        secrets = {
            'aws_access_key_id': base64.b64decode(credentials.accessKeyID).decode('utf-8'),
            'aws_secret_access_key': base64.b64decode(credentials.secretAccessKey).decode('utf-8')}
    elif cloud_provider == 'azure':
        cloud = configuration.get('azure_cloud', 'AZURE_PUBLIC_CLOUD')
        filters = {
            'virtual_machines': f'where tags contains "kubernetes.io-cluster-{shoot.status.technicalID}"'}
        configuration = {
            'azure_region': shoot.spec.region,
            'azure_resource_group': shoot.spec.provider.infrastructureConfig.resourceGroup.name if 'resourceGroup' in shoot.spec.provider.infrastructureConfig else shoot.status.technicalID,
            'azure_subscription_id': base64.b64decode(credentials['subscriptionID']).decode('utf-8')}
        secrets = {
            'azure_cloud':   cloud,
            'client_id':     base64.b64decode(credentials['clientID']).decode('utf-8'),
            'client_secret': base64.b64decode(credentials['clientSecret']).decode('utf-8'),
            'tenant_id':     base64.b64decode(credentials['tenantID']).decode('utf-8')}
    elif cloud_provider == 'gcp':
        filters = {
            'instances': f'labels.name={configuration.garden.shoot} AND labels.node_kubernetes_io_role=node AND labels.worker_gardener_cloud_pool:*', # tags such as `tags.items=kubernetes-io-cluster-shoot--core--chaos-gcp-3z` using our technical ID do not work, see https://issuetracker.google.com/issues/120255780#comment14
            'networks': f'name={shoot.status.technicalID}'}
        configuration = None
        secrets = {
            'service_account_info': json.loads(base64.b64decode(credentials['serviceaccount.json']).decode('utf-8'))}
    elif cloud_provider == 'openstack':
        filters = {
            'servers': {'metadata': 'kubernetes.io-cluster-shoot--core--chaos-os-2z'}}
        configuration = {
            'openstack_region': shoot.spec.region}
        secrets = {
            'auth_url': base64.b64decode(credentials['authURL']).decode('utf-8'),
            'user_domain_name': base64.b64decode(credentials['domainName']).decode('utf-8'),
            'username': base64.b64decode(credentials['username']).decode('utf-8'),
            'password': base64.b64decode(credentials['password']).decode('utf-8'),
            'project_domain_name': base64.b64decode(credentials['domainName']).decode('utf-8'),
            'project_name': base64.b64decode(credentials['tenantName']).decode('utf-8')}
    else:
        raise ValueError(f'Cloud provider (was {cloud_provider}) unknown/not supported!')

    # finally load module, select simulation, and return everything we got
    module = import_module(f'chaosgarden.{cloud_provider}.actions')
    simulation = getattr(module, simulation.replace(r'_cloud_provider_', r'_')) # map caller to cloud provider, e.g. `run_cloud_provider_compute_failure_simulation` -> `run_compute_failure_simulation`
    return simulation, zone, filters, configuration, secrets
