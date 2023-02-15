import random
import time
from collections import defaultdict
from datetime import datetime, timedelta
from threading import Thread
from typing import Dict, List

from com.vmware.vcenter.vm_client import Power

from chaoslib.types import Configuration, Secrets
from logzero import logger

from chaosgarden.util import (norm_filters, validate_duration, validate_mode,
                              validate_zone)
from chaosgarden.util.terminator import Terminator
from chaosgarden.util.threading import launch_thread
from chaosgarden.vsphere import (vsphere_vcenter_client,vsphere_vcenter_service_instance,list_instances,
                                 get_virtualmachines,stop_instances,start_instances,
                                 vsphere_nsxt_client,nsxt_delete_security_policy,nsxt_delete_infra_domain_group,
                                 nsxt_create_infra_domain_group,nsxt_create_security_policy,
                                 nsxt_build_expression_vm_uuids,nsxt_build_security_policy)

ZONE_TAG_NAME = 'gardener.cloud/chaos/zone'
ORIGINAL_NETWORK_ACL_ASSOCIATIONS_TAG_NAME = 'gardener.cloud/chaos/original-network-acl-associations'
ASSUMED_COMPUTE_TERMINATION_TIME_IN_SECONDS = 20
ASSUMED_COMPUTE_RESTART_TIME_IN_SECONDS = 20


__all__ = [
    'assess_filters_impact',
    'run_compute_failure_simulation_in_background',
    'run_compute_failure_simulation',
    'run_network_failure_simulation_in_background',
    'run_network_failure_simulation',
    'rollback_network_failure_simulation']


#################################
# Cloud Provider Filters Impact #
#################################

def assess_filters_impact(
        zone: str = None,
        filters: Dict[str, List[Dict[str, str]]] = None,
        configuration: Configuration = None,
        secrets: Secrets = None):
    # input validation
    validate_zone(zone)
    filters = norm_filters(filters, ['instances'], [], [])

    # report impact the given zone and filters will have
    logger.info(f'Validating client credentials and listing probably impacted instances and/or networks with the given arguments {zone=} and {filters=}:')
    client = vsphere_vcenter_client(configuration = configuration, secrets = secrets)
    instances_filter = filters['instances']
    validate_instance_filter(instances_filter)
    prefix = get_resource_pool_prefix(configuration)
    shoot_id = get_shoot_technical_id(instances_filter)
    instances = list_instances(client, zone=zone, resource_pool_prefix=prefix,shoot_technical_id=shoot_id)
    logger.info(f'{len(instances)} instance(s) would be impacted:')
    for instance in sorted(instances, key = lambda instance: instance.name):
        logger.info(f'- {instance.name} {instance.power_state}')


#############################################
# Cloud Provider Compute Failure Simulation #
#############################################

def run_compute_failure_simulation_in_background(
        mode: str = 'terminate',
        min_runtime: int = 0,
        max_runtime: int = 0,
        zone: str = None,
        filters: Dict[str, List[Dict[str, str]]] = None,
        duration: int = 0,
        configuration: Configuration = None,
        secrets: Secrets = None) -> Thread:
    return launch_thread(target = run_compute_failure_simulation, kwargs = locals())

def run_compute_failure_simulation(
        mode: str = 'terminate', # modes: 'terminate'|'restart'
        min_runtime: int = 0,
        max_runtime: int = 0,
        zone: str = None,
        filters: Dict[str, List[Dict[str, str]]] = None,
        duration: int = 0,
        configuration: Configuration = None,
        secrets: Secrets = None):
    # input validation
    validate_duration(duration)
    validate_mode(mode, ['terminate', 'restart'])
    max_runtime = max(min_runtime, max_runtime)
    validate_zone(zone)
    filters = norm_filters(filters, ['instances'], [], [])
    instances_filter = filters['instances']
    validate_instance_filter(instances_filter)
    client = vsphere_vcenter_client(configuration = configuration, secrets = secrets)
    prefix = get_resource_pool_prefix(configuration)
    shoot_id = get_shoot_technical_id(instances_filter)


    # distinguish modes
    if mode == 'terminate':
        eligible = lambda instance: instance.power_state not in ['POWERED_OFF'] # do not bother if already terminating or terminated (which stay around in AWS for quite some time anyway)
        operation = stop_instances
        reschedule_timedelta = timedelta(seconds = ASSUMED_COMPUTE_TERMINATION_TIME_IN_SECONDS) # back-off, in case termination fails silently
        need_boot_time = max_runtime > 0
    if mode == 'restart':
        eligible = lambda instance: instance.power_state not in ['POWERED_ON']
        operation = start_instances
        reschedule_timedelta = timedelta(seconds = ASSUMED_COMPUTE_RESTART_TIME_IN_SECONDS + random.randint(min_runtime, max_runtime)) # next restart
        need_boot_time = False

    # mess up instances continuously until terminated
    logger.info(f'Messing up instances matching {instances_filter["shoot_technical_id"]} in zone {zone} ({mode} between {min_runtime}s and {max_runtime}s).')
    schedule_by_name = {}
    terminator = Terminator(duration)
    while not terminator.is_terminated():
        try:
            listed_instances = list_instances(client, zone=zone, resource_pool_prefix=prefix,shoot_technical_id=shoot_id)
            if need_boot_time:
                names_to_fetch = []
                for instance in listed_instances:
                    if eligible(instance) and instance.name not in schedule_by_name:
                        names_to_fetch.append(instance.name)
                if len(names_to_fetch) > 0:
                    # REST API vmware.vapi.vsphere.client does not provide runtime information
                    # therefore need to use SOAP API to collect boot times.
                    si = vsphere_vcenter_service_instance(configuration = configuration, secrets = secrets)
                    result = get_virtualmachines(service_instance=si, vm_name_set=set(names_to_fetch))

            instances = []
            for instance in listed_instances:
                if eligible(instance):
                    if instance.name not in schedule_by_name:
                        if need_boot_time and instance.name in result:
                            schedule_by_name[instance.name] = result[instance.name].runtime.bootTime.astimezone() + timedelta(seconds = random.randint(min_runtime, max_runtime))
                        else: 
                            schedule_by_name[instance.name] = datetime.now().astimezone() - timedelta(seconds = 1)
                        logger.info(f'Scheduled instance to {mode}: {instance.name} at {schedule_by_name[instance.name]}')
                    if datetime.now().astimezone() > schedule_by_name[instance.name]:
                        schedule_by_name[instance.name] = datetime.now().astimezone() + reschedule_timedelta
                        instances.append(instance)
            operation(client, instances)
        except Exception as e:
            logger.error(f'Instances failed to {mode}: {type(e)}: {e}')
            # logger.error(traceback.format_exc())
        finally:
            time.sleep(1)


#############################################
# Cloud Provider Network Failure Simulation #
#############################################

def run_network_failure_simulation_in_background(
        mode: str = 'total',
        zone: str = None,
        filters: Dict[str, List[Dict[str, str]]] = None,
        duration: int = 0,
        configuration: Configuration = None,
        secrets: Secrets = None) -> Thread:
    return launch_thread(target = run_network_failure_simulation, kwargs = locals())

def run_network_failure_simulation(
        mode: str = 'total', # modes: 'total'|'ingress'|'egress'
        zone: str = None,
        filters: Dict[str, List[Dict[str, str]]] = None,
        duration: int = 0,
        configuration: Configuration = None,
        secrets: Secrets = None):

    # don't rollback any left-overs from hard-aborted previous simulations as they are patched anyway

    # input validation
    validate_duration(duration)
    validate_mode(mode, ['total', 'ingress', 'egress'])
    validate_zone(zone)
    filters = norm_filters(filters, ['instances'], [], [])
    instances_filter = filters['instances']
    validate_instance_filter(instances_filter)
    shoot_id = get_shoot_technical_id(instances_filter)
    uuids = get_vm_uuids(configuration=configuration,secrets=secrets,zone=zone,shoot_technical_id=shoot_id)
    client = vsphere_nsxt_client(configuration=configuration,secrets=secrets,is_policy=True)

    # block network traffic
    name = make_policy_name(zone, instances_filter)
    logger.info(f'Creating security policy {name} in DFW for zone {zone} ({mode}).')
    expr = nsxt_build_expression_vm_uuids(uuids)
    nsxt_create_infra_domain_group(client, name, [expr])
    policy=nsxt_build_security_policy(group_id=name, add_ingress_rule=mode in ['total', 'ingress'], add_egress_rule=mode in ['total', 'egress'])
    nsxt_create_security_policy(client, name, policy)

    # wait until terminated
    terminator = Terminator(duration)
    while not terminator.is_terminated():
        time.sleep(1)

    # rollback
    rollback_network_failure_simulation(mode, zone, filters, configuration, secrets)

def rollback_network_failure_simulation(
        mode: str = 'total', # modes: 'total'|'ingress'|'egress'
        zone: str = None,
        filters: Dict[str, List[Dict[str, str]]] = None,
        configuration: Configuration = None,
        secrets: Secrets = None):
    # input validation
    validate_mode(mode, ['total', 'ingress', 'egress'])
    validate_zone(zone)
    filters = norm_filters(filters, ['instances'], [], [])
    instances_filter = filters['instances']
    validate_instance_filter(instances_filter)
    client = vsphere_nsxt_client(configuration=configuration,secrets=secrets,is_policy=True)

    # rollback simulation gracefully
    name = make_policy_name(zone, instances_filter)
    logger.info(f'Deleting security policy {name} in zone {zone}.')
    nsxt_delete_security_policy(client, name)
    nsxt_delete_infra_domain_group(client, name)

def make_policy_name(zone: str, instances_filter: Dict[str,str])->str:
    shoot_technical_id = instances_filter['shoot_technical_id']
    return f'chaos-{shoot_technical_id}-{zone}'

def validate_instance_filter(instances_filter: Dict[str,str]):
    expected_keys = ['shoot_technical_id']
    for key in expected_keys:
        if not key in instances_filter:
            raise ValueError(f'Missing key {key} in instance filter')

def get_resource_pool_prefix(configuration: Configuration)->str:
    if not 'vsphere_resource_pool_prefix' in configuration:
        raise ValueError(f'Missing key vsphere_resource_pool_prefix in configuration')
    return configuration['vsphere_resource_pool_prefix']

def get_shoot_technical_id(instances_filter: Dict[str,str])->str:
    if not 'shoot_technical_id' in instances_filter:
        raise ValueError(f'Missing key shoot_technical_id in instances filter')
    return instances_filter['shoot_technical_id']

def get_vm_uuids(configuration: Configuration, secrets: Secrets, zone: str, shoot_technical_id: str)->List[str]:
    """
    Gets instance UUIDs of all instances of the given shoot cluster in the given zone
    """
    client = vsphere_vcenter_client(configuration = configuration, secrets = secrets)
    prefix = get_resource_pool_prefix(configuration)
    vms = list_instances(client, zone=zone, resource_pool_prefix=prefix, shoot_technical_id=shoot_technical_id)
    names_to_fetch = []
    for vm in vms:
        names_to_fetch.append(vm.name)
    si = vsphere_vcenter_service_instance(configuration = configuration, secrets = secrets)
    result = get_virtualmachines(service_instance=si, vm_name_set=set(names_to_fetch))
    uuids = []
    for name in result:
        uuids.append(result[name].config.instanceUuid)
    return uuids

