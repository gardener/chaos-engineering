import hashlib
import random
import time
from datetime import datetime, timedelta
from threading import Thread
from typing import Dict, List

from chaoslib.types import Configuration, Secrets
from logzero import logger

from chaosgarden.util import (norm_filters, validate_duration, validate_mode,
                              validate_zone)
from chaosgarden.util.terminator import Terminator
from chaosgarden.util.threading import launch_thread
from chaosgarden.vsphere import (delete_instances, list_instances_copy,
                                 nsxt_build_expression_vm_uuids,
                                 nsxt_build_security_policy,
                                 nsxt_create_infra_domain_group,
                                 nsxt_create_security_policy,
                                 nsxt_delete_infra_domain_group,
                                 nsxt_delete_security_policy,
                                 nsxt_get_security_policy, reset_instances,
                                 validate_virtual_machines_filter,
                                 vsphere_nsxt_client, vsphere_vcenter_client,
                                 vsphere_vcenter_service_instance)

SECURITY_POLICY_NAME_LAMBDA = lambda zone, filter, mode: f'chaosgarden-block-{mode}-{hashlib.md5(str(filter).encode("utf-8")).hexdigest()[:-16]}-{zone}'
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
    filters = norm_filters(filters, ['virtual_machines'], [], [])

    # report impact the given zone and filters will have
    logger.info(f'Validating client credentials and listing probably impacted virtual machines and/or networks with the given arguments {zone=} and {filters=}:')
    si = vsphere_vcenter_service_instance(configuration = configuration, secrets = secrets)
    virtual_machines_filter = filters['virtual_machines']
    validate_virtual_machines_filter(virtual_machines_filter)
    instances = list_instances_copy(si, zone, virtual_machines_filter)
    logger.info(f'{len(instances)} virtual machine(s) would be impacted:')
    for instance in sorted(instances, key = lambda instance: instance.name):
        logger.info(f'- {instance.name} {instance.powerState}')


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
    filters = norm_filters(filters, ['virtual_machines'], [], [])
    virtual_machines_filter = filters['virtual_machines']
    validate_virtual_machines_filter(virtual_machines_filter)
    client = vsphere_vcenter_client(configuration = configuration, secrets = secrets)
    si = vsphere_vcenter_service_instance(configuration = configuration, secrets = secrets)

    # distinguish modes
    if mode == 'terminate':
        eligible = lambda instance: instance.powerState not in ['poweredOff']
        operation = delete_instances
        reschedule_timedelta = timedelta(seconds = ASSUMED_COMPUTE_TERMINATION_TIME_IN_SECONDS) # back-off, in case termination fails silently
    if mode == 'restart':
        eligible = lambda instance: instance.powerState not in ['poweredOff']
        operation = reset_instances
        reschedule_timedelta = timedelta(seconds = ASSUMED_COMPUTE_RESTART_TIME_IN_SECONDS + random.randint(min_runtime, max_runtime)) # next restart

    # mess up instances continuously until terminated
    logger.info(f'Messing up instances matching {virtual_machines_filter} in zone {zone} ({mode} between {min_runtime}s and {max_runtime}s).')
    schedule_by_name = {}
    terminator = Terminator(duration)
    while not terminator.is_terminated():
        try:
            instances = []
            for instance in list_instances_copy(si, zone, virtual_machines_filter):
                if eligible(instance):
                    if instance.name not in schedule_by_name:
                        schedule_by_name[instance.name] = instance.bootTime.astimezone() + timedelta(seconds = random.randint(min_runtime, max_runtime))
                        logger.info(f'Scheduled virtual machine to {mode}: {instance.name} at {schedule_by_name[instance.name]}')
                    if datetime.now().astimezone() > schedule_by_name[instance.name]:
                        schedule_by_name[instance.name] = datetime.now().astimezone() + reschedule_timedelta
                        instances.append(instance)
            operation(client, instances)
        except Exception as e:
            logger.error(f'Virtual machines failed to {mode}: {type(e)}: {e}')
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
    # rollback any left-overs from hard-aborted previous simulations
    rollback_network_failure_simulation(mode, zone, filters, configuration, secrets)

    # input validation
    validate_duration(duration)
    validate_mode(mode, ['total', 'ingress', 'egress'])
    validate_zone(zone)
    filters = norm_filters(filters, ['virtual_machines'], [], [])
    virtual_machines_filter = filters['virtual_machines']
    validate_virtual_machines_filter(virtual_machines_filter)
    si = vsphere_vcenter_service_instance(configuration = configuration, secrets = secrets)
    vms_to_block = list_instances_copy(si, zone, virtual_machines_filter)
    client = vsphere_nsxt_client(configuration = configuration, secrets = secrets, is_policy = True)

    # prepare to block network traffic
    name = SECURITY_POLICY_NAME_LAMBDA(zone, virtual_machines_filter, mode)
    logger.info(f'Creating security policy {name} in DFW for zone {zone} ({mode}).')
    uuids = [vm.instanceUuid for vm in vms_to_block]
    expr = nsxt_build_expression_vm_uuids(uuids)
    nsxt_create_infra_domain_group(client, name, [expr])
    policy = nsxt_build_security_policy(group_id = name, add_ingress_rule = mode in ['total', 'ingress'], add_egress_rule = mode in ['total', 'egress'])
    nsxt_create_security_policy(client, name, policy)

    # block VMs continuously until terminated
    logger.info(f'{len(vms_to_block)} virtual machine(s) are blocked:')
    for vm in sorted(vms_to_block, key = lambda vm: vm.name):
        logger.info(f'- {vm.name}')
    included_uuids = set(uuids)
    terminator = Terminator(duration)
    while not terminator.is_terminated():
        time.sleep(1)
        vms_to_block = list_instances_copy(si, zone, virtual_machines_filter)
        new_vms = [vm for vm in vms_to_block if not vm.instanceUuid in included_uuids]
        if new_vms:
            logger.info(f'Updating domain group to block {len(new_vms)} new virtual machines.')
            for vm in sorted(new_vms, key = lambda vm: vm.name):
                logger.info(f'- {vm.name}')
            uuids = [vm.instanceUuid for vm in vms_to_block]
            expr = nsxt_build_expression_vm_uuids(uuids)
            nsxt_create_infra_domain_group(client, name, [expr])
            included_uuids = set(uuids)

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
    filters = norm_filters(filters, ['virtual_machines'], [], [])
    virtual_machines_filter = filters['virtual_machines']
    validate_virtual_machines_filter(virtual_machines_filter)
    client = vsphere_nsxt_client(configuration = configuration, secrets = secrets, is_policy = True)

    # rollback simulation gracefully
    name = SECURITY_POLICY_NAME_LAMBDA(zone, virtual_machines_filter, mode)
    logger.info(f'Deleting security policy {name} in zone {zone}.')
    nsxt_delete_security_policy(client, name)
    nsxt_delete_infra_domain_group(client, name)
    for _ in range(30):
        if not nsxt_get_security_policy(client, name):
            return
        time.sleep(1)
    raise ValueError(f'deleting security policy {name} not completed')
