import hashlib
import random
import time
from datetime import datetime, timedelta
from threading import Thread
from typing import Dict

from azure.mgmt.network.models import NetworkSecurityGroup, SecurityRule
from chaoslib.types import Configuration, Secrets
from logzero import logger

from chaosgarden.azure import (AzureClient, azure_client, create_nsg,
                               delete_nsg, delete_vm, list_nics, list_nsgs,
                               list_vms, restart_vm, update_nic,
                               wait_on_operation, wait_on_operations)
from chaosgarden.util import (norm_filters, validate_duration, validate_mode,
                              validate_zone)
from chaosgarden.util.terminator import Terminator
from chaosgarden.util.threading import launch_thread

NETWORK_SECURITY_GROUP_NAME_LAMBDA = lambda region, zone, filter: f'chaosgarden-block-{hashlib.md5(filter.encode("utf-8")).hexdigest()[:-16]}-{region}-{zone}'
ORIGINAL_NETWORK_SECURITY_GROUP_NAME_TAG_NAME = 'gardener.cloud-chaos-original-network-security-group'
ASSUMED_COMPUTE_TERMINATION_TIME_IN_SECONDS = 60
ASSUMED_COMPUTE_RESTART_TIME_IN_SECONDS = 90


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
        filters: Dict[str, str] = None,
        configuration: Configuration = None,
        secrets: Secrets = None):
    # input validation
    validate_zone(zone)
    filters = norm_filters(filters, ['virtual_machines'], [], '')

    # report impact the given zone and filters will have
    logger.info(f'Validating client credentials and listing probably impacted virtual machines with the given arguments {zone=} and {filters=}:')
    client = azure_client(configuration = configuration, secrets = secrets)
    vms = list_vms(client, configuration['azure_resource_group'], zone, filters['virtual_machines'])
    logger.info(f'{len(vms)} virtual machines(s) would be impacted:')
    for vm in sorted(vms, key = lambda vm: vm.name):
        logger.info(f'- {vm.name}')


#############################################
# Cloud Provider Compute Failure Simulation #
#############################################

def run_compute_failure_simulation_in_background(
        mode: str = 'terminate',
        min_runtime: int = 0,
        max_runtime: int = 0,
        zone: str = None,
        filters: Dict[str, str] = None,
        duration: int = 0,
        configuration: Configuration = None,
        secrets: Secrets = None) -> Thread:
    return launch_thread(target = run_compute_failure_simulation, kwargs = locals())

def run_compute_failure_simulation(
        mode: str = 'terminate', # modes: 'terminate'|'restart'
        min_runtime: int = 0,
        max_runtime: int = 0,
        zone: str = None,
        filters: Dict[str, str] = None,
        duration: int = 0,
        configuration: Configuration = None,
        secrets: Secrets = None):
    # input validation
    validate_duration(duration)
    validate_mode(mode, ['terminate', 'restart'])
    max_runtime = max(min_runtime, max_runtime)
    resource_group = configuration['azure_resource_group']
    region = configuration['azure_region']
    validate_zone(zone)
    filters = norm_filters(filters, ['virtual_machines'], [], '')
    virtual_machines_filter = filters['virtual_machines']
    client = azure_client(configuration = configuration, secrets = secrets)

    # distinguish modes
    if mode == 'terminate':
        operation = delete_vm
        reschedule_timedelta = timedelta(seconds = ASSUMED_COMPUTE_TERMINATION_TIME_IN_SECONDS) # back-off, in case termination fails silently
    if mode == 'restart':
        operation = restart_vm
        reschedule_timedelta = timedelta(seconds = ASSUMED_COMPUTE_RESTART_TIME_IN_SECONDS + random.randint(min_runtime, max_runtime)) # next restart

    # mess up instances continuously until terminated
    logger.info(f'Messing up virtual machines matching `{virtual_machines_filter}` in zone {region}-{zone} ({mode} between {min_runtime}s and {max_runtime}s).')
    schedule_by_name = {}
    terminator = Terminator(duration)
    while not terminator.is_terminated():
        try:
            for vm in list_vms(client, resource_group, zone, virtual_machines_filter):
                vm_name = vm.name
                try:
                    # strangely, the Azure VM resource contains neither status nor creation timestamp
                    if vm_name not in schedule_by_name:
                        schedule_by_name[vm_name] = datetime.now().astimezone() + timedelta(seconds = random.randint(min_runtime, max_runtime))
                        logger.info(f'Scheduled virtual machine to {mode}: {vm_name} at {schedule_by_name[vm_name]}')
                    if datetime.now().astimezone() > schedule_by_name[vm_name]:
                        schedule_by_name[vm_name] = datetime.now().astimezone() + reschedule_timedelta
                        operation(client, resource_group, zone, vm_name)
                except Exception as e:
                    logger.error(f'Virtual machine failed to {mode}: {type(e)}: {e}')
                    # logger.error(traceback.format_exc())
                    schedule_by_name[vm_name] = datetime.now().astimezone() + timedelta(seconds = 1)
        except Exception as e:
            logger.error(f'Virtual machines failed to {mode}: {type(e)}: {e}')
            # logger.error(traceback.format_exc())
        finally:
            time.sleep(2)


#############################################
# Cloud Provider Network Failure Simulation #
#############################################

def run_network_failure_simulation_in_background(
        mode: str = 'total',
        zone: str = None,
        filters: Dict[str, str] = None,
        duration: int = 0,
        configuration: Configuration = None,
        secrets: Secrets = None) -> Thread:
    return launch_thread(target = run_network_failure_simulation, kwargs = locals())

def run_network_failure_simulation(
        mode: str = 'total', # modes: 'total'|'ingress'|'egress'
        zone: str = None,
        filters: Dict[str, str] = None,
        duration: int = 0,
        configuration: Configuration = None,
        secrets: Secrets = None):
    # rollback any left-overs from hard-aborted previous simulations
    rollback_network_failure_simulation(mode, zone, filters, configuration, secrets)

    # input validation
    validate_duration(duration)
    validate_mode(mode, ['total', 'ingress', 'egress'])
    resource_group = configuration['azure_resource_group']
    region = configuration['azure_region']
    validate_zone(zone)
    filters = norm_filters(filters, ['virtual_machines'], [], '')
    virtual_machines_filter = filters['virtual_machines']
    client = azure_client(configuration = configuration, secrets = secrets)

    # prepare to block network traffic
    logger.info(f'Partitioning virtual networks with virtual machines matching `{virtual_machines_filter}` in zone {region}-{zone} ({mode}).')
    blocking_nsg = create_blocking_network_security_group(client, resource_group, region, zone, virtual_machines_filter, mode)
    block_virtual_machines(client, resource_group, region, zone, virtual_machines_filter, blocking_nsg)

    # block VMs continuously until terminated
    terminator = Terminator(duration)
    while not terminator.is_terminated():
        try:
            block_virtual_machines(client, resource_group, region, zone, virtual_machines_filter, blocking_nsg)
        except Exception as e:
            logger.error(f'Virtual machine blocking failed: {type(e)}: {e}')
            # logger.error(traceback.format_exc())
        finally:
            time.sleep(2)

    # rollback
    rollback_network_failure_simulation(mode, zone, filters, configuration, secrets)

def rollback_network_failure_simulation(
        mode: str = 'total', # modes: 'total'|'ingress'|'egress'
        zone: str = None,
        filters: Dict[str, str] = None,
        configuration: Configuration = None,
        secrets: Secrets = None):
    # input validation
    validate_mode(mode, ['total', 'ingress', 'egress'])
    resource_group = configuration['azure_resource_group']
    region = configuration['azure_region']
    validate_zone(zone)
    filters = norm_filters(filters, ['virtual_machines'], [], '')
    virtual_machines_filter = filters['virtual_machines']
    client = azure_client(configuration = configuration, secrets = secrets)

    # rollback simulation gracefully
    logger.info(f'Unpartitioning virtual networks with virtual machines matching `{virtual_machines_filter}` in zone {region}-{zone} ({mode}).')
    unblock_virtual_machines(client, resource_group, region, zone, virtual_machines_filter)
    delete_blocking_network_security_group(client, resource_group, region, zone, virtual_machines_filter)

def create_blocking_network_security_group(
        client: AzureClient,
        resource_group: str,
        region: str,
        zone: str,
        virtual_machines_filter: str,
        mode: str) -> NetworkSecurityGroup:
    # create blocking NSG
    nsg = NetworkSecurityGroup()
    nsg.name = NETWORK_SECURITY_GROUP_NAME_LAMBDA(region, zone, virtual_machines_filter)
    nsg.location = region
    nsg.security_rules = []
    modes = ['ingress', 'egress'] if mode == 'total' else [mode]
    for mode in modes:
        nsg.security_rules.append(SecurityRule(
            name                       = f'DenyAll{mode.title()}',
            description                = f'Deny {mode} network traffic while chaosgarden action runs that partitions networks with virtual machines in zone {region}-{zone}'[:140],
            priority                   = 100, # lowest possible rank
            access                     = 'Deny',
            direction                  = 'Inbound' if mode == 'ingress' else 'Outbound',
            protocol                   = '*',
            source_address_prefix      = '*',
            source_port_range          = '*',
            destination_address_prefix = '*',
            destination_port_range     = '*'))
    nsg = wait_on_operation(create_nsg(client, resource_group, nsg))
    logger.info(f'Created blocking network security group {nsg.name}.')
    return nsg

def delete_blocking_network_security_group(
        client: AzureClient,
        resource_group: str,
        region: str,
        zone: str,
        virtual_machines_filter: str):
    # delete blocking NSG
    nsg_name = NETWORK_SECURITY_GROUP_NAME_LAMBDA(region, zone, virtual_machines_filter)
    wait_on_operation(delete_nsg(client, resource_group, nsg_name))
    logger.info(f'Deleted blocking network security group {nsg_name} (if any).')

def block_virtual_machines(
        client: AzureClient,
        resource_group: str,
        region: str,
        zone: str,
        virtual_machines_filter: str,
        blocking_nsg: NetworkSecurityGroup):
    # list all VMs in zone
    vms = {vm.id.lower(): vm for vm in list_vms(client, resource_group, zone, virtual_machines_filter)}

    # list all NICs and associate not blocked NICs with the blocking NSG and restart their virtual machines
    vms_to_block = []
    operations = []
    for nic in list_nics(client, resource_group):
        if nic.virtual_machine and nic.virtual_machine.id.lower() in vms and ORIGINAL_NETWORK_SECURITY_GROUP_NAME_TAG_NAME not in nic.tags:
            nic.tags[ORIGINAL_NETWORK_SECURITY_GROUP_NAME_TAG_NAME] = nic.network_security_group.id.lower() if nic.network_security_group else ''
            nic.network_security_group = blocking_nsg
            try:
                operations.append(update_nic(client, resource_group, nic))
                vms_to_block.append(vms[nic.virtual_machine.id.lower()])
            except:
                # probably a consistency issue/race condition/outdated cache in ARM, and if it's not, we will try again next time
                pass
    if operations:
        wait_on_operations(operations)
        operations = []
        for vm in vms_to_block:
            try:
                operations.append(restart_vm(client, resource_group, zone, vm.name))
            except Exception as e:
                logger.error(f'Failed to restart VM {vm.name}: {type(e)}: {e}')
        wait_on_operations(operations)
        logger.info(f'Blocked and restarted {len(operations)} virtual machines.')

def unblock_virtual_machines(
        client: AzureClient,
        resource_group: str,
        region: str,
        zone: str,
        virtual_machines_filter: str):
    # list all NSGs
    nsgs = {nsg.id.lower(): nsg for nsg in list_nsgs(client, resource_group)}
    nsgs[''] = None

    # list all VMs in zone
    vms = {vm.id.lower(): vm for vm in list_vms(client, resource_group, zone, virtual_machines_filter)}

    # list all NICs and reassociate blocked NICs with their original NSG (if any) and restart their virtual machines
    vms_to_unblock = []
    operations = []
    for nic in list_nics(client, resource_group):
        if nic.virtual_machine and nic.virtual_machine.id.lower() in vms and ORIGINAL_NETWORK_SECURITY_GROUP_NAME_TAG_NAME in nic.tags:
            nic.network_security_group = nsgs[nic.tags[ORIGINAL_NETWORK_SECURITY_GROUP_NAME_TAG_NAME]]
            del nic.tags[ORIGINAL_NETWORK_SECURITY_GROUP_NAME_TAG_NAME]
            try:
                operations.append(update_nic(client, resource_group, nic))
                vms_to_unblock.append(vms[nic.virtual_machine.id.lower()])
            except Exception as e:
                # probably a consistency issue/race condition/outdated cache in ARM, but if it's not, we should log it as error for the end user to notice
                if nic.network_security_group:
                    logger.error(f'Failed to reassociate blocked network interface {nic.name} for VM {nic.virtual_machine.id.lower()} with original network security group {nic.network_security_group}: {type(e)}: {e}')
                else:
                    logger.error(f'Failed to disassociate blocked network interface {nic.name} for VM {nic.virtual_machine.id.lower()} from blocking network security group: {type(e)}: {e}')
    if operations:
        wait_on_operations(operations)
        operations = []
        for vm in vms_to_unblock:
            try:
                operations.append(restart_vm(client, resource_group, zone, vm.name))
            except Exception as e:
                logger.error(f'Failed to restart VM {vm.name}: {type(e)}: {e}')
        wait_on_operations(operations)
        logger.info(f'Unblocked and restarted {len(operations)} virtual machines.')
