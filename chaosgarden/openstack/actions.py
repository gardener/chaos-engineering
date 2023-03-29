import hashlib
import random
import time
from datetime import datetime, timedelta
from threading import Thread
from typing import Dict

from chaoslib.types import Configuration, Secrets
from logzero import logger

from chaosgarden.openstack import (create_sg, delete_sg, list_servers,
                                   openstack_connection, restart_server,
                                   terminate_server)
from chaosgarden.util import (norm_filters, validate_duration, validate_mode,
                              validate_zone)
from chaosgarden.util.terminator import Terminator
from chaosgarden.util.threading import launch_thread

SECURITY_GROUP_NAME_LAMBDA = lambda zone, filter: f'chaosgarden-block-{hashlib.md5(str(filter).encode("utf-8")).hexdigest()[:-16]}-{zone}'
ORIGINAL_SECURITY_GROUP_NAMES_METADATA_NAME = 'gardener.cloud-chaos-original-security-group'
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
        filters: Dict[str, Dict[str, str]] = None,
        configuration: Configuration = None,
        secrets: Secrets = None):
    # input validation
    validate_zone(zone)
    filters = norm_filters(filters, ['servers'], [], {})

    # report impact the given zone and filters will have
    logger.info(f'Validating client credentials and listing probably impacted servers with the given arguments {zone=} and {filters=}:')
    conn = openstack_connection(configuration, secrets)
    servers = list_servers(conn, zone, None, filters['servers'])
    logger.info(f'{len(servers)} server(s) would be impacted:')
    for server in sorted(servers, key = lambda server: server.name):
        logger.info(f'- {server.name}')


#############################################
# Cloud Provider Compute Failure Simulation #
#############################################

def run_compute_failure_simulation_in_background(
        mode: str = 'terminate',
        min_runtime: int = 0,
        max_runtime: int = 0,
        zone: str = None,
        filters: Dict[str, Dict[str, str]] = None,
        duration: int = 0,
        configuration: Configuration = None,
        secrets: Secrets = None) -> Thread:
    return launch_thread(target = run_compute_failure_simulation, kwargs = locals())

def run_compute_failure_simulation(
        mode: str = 'terminate', # modes: 'terminate'|'restart'
        min_runtime: int = 0,
        max_runtime: int = 0,
        zone: str = None,
        filters: Dict[str, Dict[str, str]] = None,
        duration: int = 0,
        configuration: Configuration = None,
        secrets: Secrets = None):
    # input validation
    validate_duration(duration)
    validate_mode(mode, ['terminate', 'restart'])
    max_runtime = max(min_runtime, max_runtime)
    validate_zone(zone)
    filters = norm_filters(filters, ['servers'], [], {})
    servers_filter = filters['servers']
    conn = openstack_connection(configuration, secrets)

    # distinguish modes
    if mode == 'terminate':
        status = None
        operation = terminate_server
        reschedule_timedelta = timedelta(seconds = ASSUMED_COMPUTE_TERMINATION_TIME_IN_SECONDS) # back-off, in case termination fails silently
    if mode == 'restart':
        status = ['ACTIVE']
        operation = restart_server
        reschedule_timedelta = timedelta(seconds = ASSUMED_COMPUTE_RESTART_TIME_IN_SECONDS + random.randint(min_runtime, max_runtime)) # next restart

    # mess up servers continuously until terminated
    logger.info(f'Messing up servers matching {servers_filter} in zone {zone} ({mode} between {min_runtime}s and {max_runtime}s).')
    schedule_by_name = {}
    terminator = Terminator(duration)
    while not terminator.is_terminated():
        try:
            for server in list_servers(conn, zone, status, servers_filter):
                server_name = server.name
                try:
                    if server_name not in schedule_by_name:
                        schedule_by_name[server_name] = datetime.fromisoformat(server.created_at.replace('Z', '+00:00')) + timedelta(seconds = random.randint(min_runtime, max_runtime))
                        logger.info(f'Scheduled server to {mode}: {server_name} at {schedule_by_name[server_name]}')
                    if datetime.now().astimezone() > schedule_by_name[server_name]:
                        schedule_by_name[server_name] = datetime.now().astimezone() + reschedule_timedelta
                        operation(conn, server)
                except Exception as e:
                    logger.error(f'Server failed to {mode}: {type(e)}: {e}')
                    # logger.error(traceback.format_exc())
                    schedule_by_name[server_name] = datetime.now().astimezone() + timedelta(seconds = 1)
        except Exception as e:
            logger.error(f'Servers failed to {mode}: {type(e)}: {e}')
            # logger.error(traceback.format_exc())
        finally:
            time.sleep(1)


#############################################
# Cloud Provider Network Failure Simulation #
#############################################

def run_network_failure_simulation_in_background(
        mode: str = 'total',
        zone: str = None,
        filters: Dict[str, Dict[str, str]] = None,
        duration: int = 0,
        configuration: Configuration = None,
        secrets: Secrets = None) -> Thread:
    return launch_thread(target = run_network_failure_simulation, kwargs = locals())

def run_network_failure_simulation(
        mode: str = 'total', # modes: 'total'|'ingress'|'egress'
        zone: str = None,
        filters: Dict[str, Dict[str, str]] = None,
        duration: int = 0,
        configuration: Configuration = None,
        secrets: Secrets = None):
    # rollback any left-overs from hard-aborted previous simulations
    rollback_network_failure_simulation(mode, zone, filters, configuration, secrets)

    # input validation
    validate_duration(duration)
    validate_mode(mode, ['total', 'ingress', 'egress'])
    validate_zone(zone)
    filters = norm_filters(filters, ['servers'], [], {})
    servers_filter = filters['servers']
    conn = openstack_connection(configuration, secrets)

    # prepare to block network traffic
    logger.info(f'Partitioning networks with servers matching {servers_filter} in zone {zone} ({mode}).')
    create_blocking_security_group(conn, zone, servers_filter, mode)
    block_servers(conn, zone, servers_filter)

    # block servers continuously until terminated
    terminator = Terminator(duration)
    while not terminator.is_terminated():
        try:
            block_servers(conn, zone, servers_filter)
        except Exception as e:
            logger.error(f'Server blocking failed: {type(e)}: {e}')
            # logger.error(traceback.format_exc())
        finally:
            time.sleep(1)

    # rollback
    rollback_network_failure_simulation(mode, zone, filters, configuration, secrets)

def rollback_network_failure_simulation(
        mode: str = 'total', # modes: 'total'|'ingress'|'egress'
        zone: str = None,
        filters: Dict[str, Dict[str, str]] = None,
        configuration: Configuration = None,
        secrets: Secrets = None):
    # input validation
    validate_mode(mode, ['total', 'ingress', 'egress'])
    validate_zone(zone)
    filters = norm_filters(filters, ['servers'], [], {})
    servers_filter = filters['servers']
    conn = openstack_connection(configuration, secrets)

    # rollback simulation gracefully
    logger.info(f'Unpartitioning networks with servers matching {servers_filter} in zone {zone} ({mode}).')
    unblock_servers(conn, zone, servers_filter)
    delete_blocking_security_group(conn, zone, servers_filter)

def create_blocking_security_group(conn, zone, servers_filter, mode):
    # create blocking SG
    # https://opendev.org/openstack/openstacksdk/src/branch/master/openstack/network/v2/security_group.py
    sg_attrs = {
        'name':        SECURITY_GROUP_NAME_LAMBDA(zone, servers_filter),
        'description': f'Deny {mode} network traffic while chaosgarden action runs that partitions networks with servers matching {servers_filter} in zone {zone}.'}
    sgr_attrs_list = []
    if mode != 'total':
        direction = 'egress' if mode == 'ingress' else 'ingress'
        for ether_type in ['IPv4', 'IPv6']:
            # https://opendev.org/openstack/openstacksdk/src/branch/master/openstack/network/v2/security_group_rule.py
            sgr_attrs_list.append({
                'description': f'Allow {direction} network traffic while chaosgarden action runs',
                'direction':   direction,
                'ether_type':  ether_type,
                'protocol':    None})
    sg = create_sg(conn, sg_attrs, sgr_attrs_list)
    logger.info(f'Created blocking network security group {sg.name}.')
    return sg

def delete_blocking_security_group(conn, zone, servers_filter):
    # delete blocking SG
    sg_name = SECURITY_GROUP_NAME_LAMBDA(zone, servers_filter)
    if delete_sg(conn, sg_name):
        logger.info(f'Deleted blocking security group {sg_name}.')

def block_servers(conn, zone, servers_filter):
    # list all servers and associate not blocked servers with the blocking SG
    blocked = 0
    for server in list_servers(conn, zone, 'ACTIVE', servers_filter):
        if ORIGINAL_SECURITY_GROUP_NAMES_METADATA_NAME not in server.metadata:
            server.set_metadata_item(session = conn.compute, key = ORIGINAL_SECURITY_GROUP_NAMES_METADATA_NAME, value = ';'.join([sg['name'] for sg in server.security_groups]))
        has_original_sg = False
        has_blocking_sg = False
        for sg in server.security_groups:
            sg_name = sg['name']
            if sg_name != SECURITY_GROUP_NAME_LAMBDA(zone, servers_filter):
                has_original_sg = True
                try:
                    logger.info(f'Removing original security group {sg_name} from server {server.name}.')
                    conn.compute.remove_security_group_from_server(server, security_group = {'name': sg_name})
                except Exception as e:
                    logger.error(f'Removing original security group {sg_name} from server {server.name} failed: {type(e)}: {e}')
            else:
                has_blocking_sg = True
        if not has_blocking_sg:
            try:
                logger.info(f'Adding blocking security group {SECURITY_GROUP_NAME_LAMBDA(zone, servers_filter)} to server {server.name}.')
                conn.compute.add_security_group_to_server(server, security_group = {'name': SECURITY_GROUP_NAME_LAMBDA(zone, servers_filter)})
            except Exception as e:
                logger.error(f'Adding blocking security group {SECURITY_GROUP_NAME_LAMBDA(zone, servers_filter)} to server {server.name} failed: {type(e)}: {e}')
        if has_original_sg or not has_blocking_sg:
            blocked += 1
    if blocked:
        logger.info(f'Blocked {blocked} servers.')

def unblock_servers(conn, zone, servers_filter):
    # list all servers and reassociate blocked servers with the original SGs
    unblocked = 0
    for server in list_servers(conn, zone, None, servers_filter):
        if ORIGINAL_SECURITY_GROUP_NAMES_METADATA_NAME in server.metadata:
            sg_names = server.metadata[ORIGINAL_SECURITY_GROUP_NAMES_METADATA_NAME].split(';')
            for sg_name in sg_names:
                try:
                    conn.compute.add_security_group_to_server(server, security_group = {'name': sg_name})
                except Exception as e:
                    logger.error(f'Adding original security group {sg_name} to server {server.name} failed: {type(e)}: {e}')
            try:
                conn.compute.remove_security_group_from_server(server, security_group = {'name': SECURITY_GROUP_NAME_LAMBDA(zone, servers_filter)})
            except Exception as e:
                logger.error(f'Removing blocking security group {SECURITY_GROUP_NAME_LAMBDA(zone, servers_filter)} from server {server.name} failed: {type(e)}: {e}')
            server = conn.compute.get_server(server)
            if {sg['name'] for sg in server.security_groups} == set(sg_names):
                server.delete_metadata_item(session = conn.compute, key = ORIGINAL_SECURITY_GROUP_NAMES_METADATA_NAME)
            else:
                logger.error(f'Unblocking server {server.name} failed: original security groups {server.metadata[ORIGINAL_SECURITY_GROUP_NAMES_METADATA_NAME]} could not be restored and are ' + ';'.join([sg['name'] for sg in server.security_groups]))
            unblocked += 1
    if unblocked:
        logger.info(f'Unblocked {unblocked} servers.')
