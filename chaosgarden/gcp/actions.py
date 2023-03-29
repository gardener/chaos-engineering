import hashlib
import random
import time
from datetime import datetime, timedelta
from threading import Thread
from typing import Dict, Tuple

from chaosgcp import client as gcp_client
from chaoslib.types import Configuration, Secrets
from logzero import logger

from chaosgarden.gcp import (create_firewall, delete_firewall, list_firewalls,
                             list_instances, list_networks,
                             project_id_from_secrets, restart_instance,
                             resume_instance, suspend_instance, tag_instance,
                             terminate_instance, wait_on_global_operations,
                             wait_on_zonal_operations)
from chaosgarden.util import (norm_filters, validate_duration, validate_mode,
                              validate_zone)
from chaosgarden.util.terminator import Terminator
from chaosgarden.util.threading import launch_thread

FIREWALL_NAME_LAMBDA = lambda zone, filter, mode: f'chaosgarden-block-{mode}-{hashlib.md5(filter.encode("utf-8")).hexdigest()[:-16]}-{zone}'
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
        filters: Dict[str, str] = None,
        configuration: Configuration = None,
        secrets: Secrets = None):
    # input validation
    validate_zone(zone)
    filters = norm_filters(filters, ['instances'], ['networks'], '')

    # report impact the given zone and filters will have
    logger.info(f'Validating client credentials and listing probably impacted instances and/or networks with the given arguments {zone=} and {filters=}:')
    client = gcp_client(service_name = 'compute', version = 'v1', secrets = secrets)
    instances = list_instances(client, project_id_from_secrets(secrets), zone, filters['instances'])
    logger.info(f'{len(instances)} instance(s) would be impacted:')
    for instance in sorted(instances, key = lambda instance: instance.name):
        logger.info(f'- {instance["name"]}')
    networks = list_networks(client, project_id_from_secrets(secrets), filters['networks'])
    logger.info(f'{len(networks)} network(s) would be impacted:')
    for network in sorted(networks, key = lambda network: network.name):
        logger.info(f'- {network["name"]}')


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
    project = project_id_from_secrets(secrets)
    validate_zone(zone)
    filters = norm_filters(filters, ['instances'], ['networks'], '')
    instances_filter = filters['instances']
    client = gcp_client(service_name = 'compute', version = 'v1', secrets = secrets)

    # distinguish modes
    if mode == 'terminate':
        eligible = lambda instance: instance['status'].lower() not in ['pending', 'staging', 'stopping'] # you cannot terminate pending/staging instances that are coming up in GCP, so we must be patient
        operation = terminate_instance
        reschedule_timedelta = timedelta(seconds = ASSUMED_COMPUTE_TERMINATION_TIME_IN_SECONDS) # back-off, in case termination fails silently
    if mode == 'restart':
        eligible = lambda instance: instance['status'].lower() in ['running']
        operation = restart_instance
        reschedule_timedelta = timedelta(seconds = ASSUMED_COMPUTE_RESTART_TIME_IN_SECONDS + random.randint(min_runtime, max_runtime)) # next restart

    # mess up instances continuously until terminated
    logger.info(f'Messing up instances matching `{instances_filter}` in zone {zone} ({mode} between {min_runtime}s and {max_runtime}s).')
    schedule_by_name = {}
    terminator = Terminator(duration)
    while not terminator.is_terminated():
        try:
            for instance in list_instances(client, project, zone, instances_filter):
                instance_name = instance['name']
                try:
                    if eligible(instance):
                        if instance_name not in schedule_by_name:
                            schedule_by_name[instance_name] = datetime.fromisoformat(instance['creationTimestamp']) + timedelta(seconds = random.randint(min_runtime, max_runtime))
                            logger.info(f'Scheduled instance to {mode}: {instance_name} at {schedule_by_name[instance_name]}')
                        if datetime.now().astimezone() > schedule_by_name[instance_name]:
                            schedule_by_name[instance_name] = datetime.now().astimezone() + reschedule_timedelta
                            operation(client, project, zone, instance_name)
                except Exception as e:
                    logger.error(f'Instance failed to {mode}: {type(e)}: {e}')
                    # logger.error(traceback.format_exc())
                    schedule_by_name[instance_name] = datetime.now().astimezone() + timedelta(seconds = 1)
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
        filters: Dict[str, str] = None,
        duration: int = 0,
        configuration: Configuration = None,
        secrets: Secrets = None) -> Thread:
    return launch_thread(target = run_network_failure_simulation, kwargs = locals())

def run_network_failure_simulation(
        mode: str = 'total', # modes: 'total'|'ingress'|'egress' with possible suffix '_with_instance_restart' to restart instead of suspend/resume the instance to terminate existing connections (see suspend/resume limitations https://cloud.google.com/compute/docs/instances/suspend-resume-instance#limitations)
        zone: str = None,
        filters: Dict[str, str] = None,
        duration: int = 0,
        configuration: Configuration = None,
        secrets: Secrets = None):
    # rollback any left-overs from hard-aborted previous simulations
    rollback_network_failure_simulation(mode, zone, filters, configuration, secrets)

    # input validation
    validate_duration(duration)
    mode, requires_restart = parse_mode(mode)
    validate_mode(mode, ['total', 'ingress', 'egress'])
    project = project_id_from_secrets(secrets)
    validate_zone(zone)
    filters = norm_filters(filters, ['instances', 'networks'], [], '')
    instances_filter = filters['instances']
    networks_filter  = filters['networks']
    client = gcp_client(service_name = 'compute', version = 'v1', secrets = secrets)

    # prepare to block network traffic
    logger.info(f'Partitioning networks matching `{networks_filter}` with instances matching `{instances_filter}` in zone {zone} ({mode} with instance {"restart" if requires_restart else "suspend/resume"}).')
    for network in list_networks(client, project, networks_filter):
        create_blocking_firewalls(client, project, zone, instances_filter, network['selfLink'], mode)
    block_instances(client, project, zone, instances_filter, requires_restart)

    # block instances continuously until terminated
    terminator = Terminator(duration)
    while not terminator.is_terminated():
        try:
            block_instances(client, project, zone, instances_filter, requires_restart)
        except Exception as e:
            logger.error(f'Instance blocking failed: {type(e)}: {e}')
            # logger.error(traceback.format_exc())
        finally:
            time.sleep(1)

    # rollback
    rollback_network_failure_simulation(mode, zone, filters, configuration, secrets)

def rollback_network_failure_simulation(
        mode: str = 'total', # modes: 'total'|'ingress'|'egress' with possible suffix '_with_instance_restart' to restart instead of suspend/resume the instance to terminate existing connections (see suspend/resume limitations https://cloud.google.com/compute/docs/instances/suspend-resume-instance#limitations)
        zone: str = None,
        filters: Dict[str, str] = None,
        configuration: Configuration = None,
        secrets: Secrets = None):
    # input validation
    mode, _ = parse_mode(mode)
    validate_mode(mode, ['total', 'ingress', 'egress'])
    project = project_id_from_secrets(secrets)
    validate_zone(zone)
    filters = norm_filters(filters, ['instances', 'networks'], [], '')
    instances_filter = filters['instances']
    networks_filter  = filters['networks']
    client = gcp_client(service_name = 'compute', version = 'v1', secrets = secrets)

    # rollback simulation gracefully
    logger.info(f'Unpartitioning networks matching `{networks_filter}` with instances matching `{instances_filter}` in zone {zone} ({mode}).')
    unblock_instances(client, project, zone, instances_filter)
    delete_blocking_firewalls(client, project, zone, instances_filter)

def parse_mode(mode: str) -> Tuple[str, str]:
    requires_restart = False
    if mode.endswith('_with_instance_restart'):
        requires_restart = True
        mode = mode.replace('_with_instance_restart', '')
    return mode, requires_restart

def create_blocking_firewalls(client, project, zone, instances_filter, network_link, mode):
    # create blocking firewalls
    operations = []
    modes = ['ingress', 'egress'] if mode == 'total' else [mode]
    for mode in modes:
        firewall_name = FIREWALL_NAME_LAMBDA(zone, instances_filter, mode)
        firewall_body = {
            'name': firewall_name,
            'description': f'Deny {mode} network traffic while chaosgarden action runs that partitions networks with instances matching `{instances_filter}` in zone {zone}',
            'network': network_link,
            'priority': 0, # lowest possible rank
            'sourceRanges' if mode == 'ingress' else 'destinationRanges': ['0.0.0.0/0'],
            'targetTags': [FIREWALL_NAME_LAMBDA(zone, instances_filter, 'tag')],
            'denied': [{'IPProtocol': 'all'}],
            'direction': mode.upper()}
        operations.append(create_firewall(client, project, firewall_name, firewall_body))
    wait_on_global_operations(client, project, operations)
    logger.info(f'Created blocking firewalls.')

def delete_blocking_firewalls(client, project, zone, instances_filter):
    # delete blocking firewalls
    firewalls_filter = f'name eq ' + FIREWALL_NAME_LAMBDA(zone, instances_filter, '[^-]+')
    operations = []
    for firewall in list_firewalls(client, project, firewalls_filter):
        operations.append(delete_firewall(client, project, firewall['name']))
    if operations:
        wait_on_global_operations(client, project, operations)
        logger.info(f'Deleted {len(operations)} blocking firewalls.')

def block_instances(client, project, zone, instances_filter, requires_restart):
    # list all not blocked instances and tag, suspend, and resume them
    firewall_network_tag = FIREWALL_NAME_LAMBDA(zone, instances_filter, 'tag')
    instances_to_block = []
    for instance in list_instances(client, project, zone, instances_filter):
        if firewall_network_tag not in instance['tags']['items']:
            instances_to_block.append(instance)
    if instances_to_block:
        instances_to_interrupt = []
        operations = []
        for instance in instances_to_block:
            try:
                operations.append(tag_instance(client, project, zone, instance['name'], instance['tags']['items'] + [firewall_network_tag], instance['tags']['fingerprint']))
                instances_to_interrupt.append(instance)
            except Exception as e:
                logger.error(f'Failed to tag instance {instance["name"]}: {type(e)}: {e}')
        wait_on_zonal_operations(client, project, zone, operations)
        if requires_restart:
            operations = []
            for instance in instances_to_interrupt:
                try:
                    operations.append(restart_instance(client, project, zone, instance['name']))
                except Exception as e:
                    logger.error(f'Failed to restart instance {instance["name"]}: {type(e)}: {e}')
            wait_on_zonal_operations(client, project, zone, operations)
        else:
            instances_to_resume = []
            operations = []
            for instance in instances_to_interrupt:
                try:
                    operations.append(suspend_instance(client, project, zone, instance['name']))
                    instances_to_resume.append(instance)
                except Exception as e:
                    logger.error(f'Failed to suspend instance {instance["name"]}: {type(e)}: {e}')
            wait_on_zonal_operations(client, project, zone, operations)
            operations = []
            for instance in instances_to_resume:
                try:
                    operations.append(resume_instance(client, project, zone, instance['name']))
                except Exception as e:
                    logger.error(f'Failed to resume instance {instance["name"]}: {type(e)}: {e}')
            wait_on_zonal_operations(client, project, zone, operations)
        logger.info(f'Blocked and interrupted {len(operations)} instances.')

def unblock_instances(client, project, zone, instances_filter):
    # list all blocked instances and untag them
    firewall_network_tag = FIREWALL_NAME_LAMBDA(zone, instances_filter, 'tag')
    operations = []
    for instance in list_instances(client, project, zone, instances_filter):
        if firewall_network_tag in instance['tags']['items']:
            try:
                operations.append(tag_instance(client, project, zone, instance['name'], [tag for tag in instance['tags']['items'] if tag != firewall_network_tag], instance['tags']['fingerprint']))
            except Exception as e:
                logger.error(f'Failed to untag instance {instance["name"]}: {type(e)}: {e}')
    if operations:
        wait_on_zonal_operations(client, project, zone, operations)
        logger.info(f'Unblocked {len(operations)} instances.')
