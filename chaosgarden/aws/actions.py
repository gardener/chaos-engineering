import hashlib
import random
import time
from collections import defaultdict
from datetime import datetime, timedelta
from threading import Thread
from typing import Dict, List

from chaosaws import aws_client
from chaosaws.ec2.actions import (list_instances, restart_instances_any_type,
                                  terminate_instances_any_type)
from chaoslib.types import Configuration, Secrets
from logzero import logger

from chaosgarden.util import (norm_filters, validate_duration, validate_mode,
                              validate_zone)
from chaosgarden.util.terminator import Terminator
from chaosgarden.util.threading import launch_thread

ZONE_TAG_NAME_LAMBDA = lambda zone, filter: f'gardener.cloud/chaos/chaosgarden-block-{hashlib.md5(str(filter).encode("utf-8")).hexdigest()[:-16]}-{zone}'
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
    filters = norm_filters(filters, ['instances', 'vpcs'], ['subnets'], [])

    # report impact the given zone and filters will have
    logger.info(f'Validating client credentials and listing probably impacted instances and/or networks with the given arguments {zone=} and {filters=}:')
    client = aws_client(resource_name = 'ec2', configuration = configuration, secrets = secrets)
    instances_filter = list(filters['instances'])
    instances_filter.append({'Name': 'availability-zone', 'Values': [zone]})
    instances_filter.append({'Name': 'instance-state-name', 'Values': ['pending', 'running', 'stopping', 'stopped']})
    instances = list_instances(client, instances_filter)
    logger.info(f'{len(instances)} instance(s) would be impacted:')
    for instance in sorted(instances, key = lambda instance: instance["InstanceId"]):
        logger.info(f'- {instance["InstanceId"]}')
    vpcs = client.describe_vpcs(Filters = filters['vpcs'])['Vpcs']
    logger.info(f'{len(vpcs)} VPC(s) would be impacted:')
    for vpc in sorted(vpcs, key = lambda vpc: vpc["VpcId"]):
        logger.info(f'- {vpc["VpcId"]}')


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
    filters = norm_filters(filters, ['instances'], ['vpcs', 'subnets'], [])
    instances_filter = filters['instances']
    client = aws_client(resource_name = 'ec2', configuration = configuration, secrets = secrets)

    # distinguish modes
    if mode == 'terminate':
        eligible = lambda instance: instance['State']['Name'].lower() not in ['shutting-down', 'terminated'] # do not bother if already terminating or terminated (which stay around in AWS for quite some time anyway)
        operation = terminate_instances_any_type
        reschedule_timedelta = timedelta(seconds = ASSUMED_COMPUTE_TERMINATION_TIME_IN_SECONDS) # back-off, in case termination fails silently
    if mode == 'restart':
        eligible = lambda instance: instance['State']['Name'].lower() in ['running']
        operation = restart_instances_any_type
        reschedule_timedelta = timedelta(seconds = ASSUMED_COMPUTE_RESTART_TIME_IN_SECONDS + random.randint(min_runtime, max_runtime)) # next restart

    # mess up instances continuously until terminated
    logger.info(f'Messing up instances matching {instances_filter} in zone {zone} ({mode} between {min_runtime}s and {max_runtime}s).')
    instances_filter = list(instances_filter)
    instances_filter.append({'Name': 'availability-zone', 'Values': [zone]})
    schedule_by_id = {}
    terminator = Terminator(duration)
    while not terminator.is_terminated():
        try:
            instances_by_type = defaultdict(list)
            for instance in list_instances(client, instances_filter):
                instance_id = instance['InstanceId']
                if eligible(instance):
                    if instance_id not in schedule_by_id:
                        schedule_by_id[instance_id] = instance['LaunchTime'] + timedelta(seconds = random.randint(min_runtime, max_runtime))
                        logger.info(f'Scheduled instance to {mode}: {instance_id} at {schedule_by_id[instance_id]}')
                    if datetime.now().astimezone() > schedule_by_id[instance_id]:
                        schedule_by_id[instance_id] = datetime.now().astimezone() + reschedule_timedelta
                        instances_by_type[instance.get('InstanceLifecycle', 'normal')].append(instance_id)
            operation(instances_by_type, client)
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
    # rollback any left-overs from hard-aborted previous simulations
    rollback_network_failure_simulation(mode, zone, filters, configuration, secrets)

    # input validation
    validate_duration(duration)
    validate_mode(mode, ['total', 'ingress', 'egress'])
    validate_zone(zone)
    filters = norm_filters(filters, ['vpcs', 'subnets'], ['instances'], [])
    vpcs_filter = filters['vpcs']
    subnets_filter = filters['subnets']
    client = aws_client(resource_name = 'ec2', configuration = configuration, secrets = secrets)

    # block network traffic
    logger.info(f'Partitioning VPCs matching {vpcs_filter} in zone {zone} ({mode}).')
    for vpc in client.describe_vpcs(Filters = vpcs_filter)['Vpcs']:
        block_vpc(client, zone, vpc['VpcId'], subnets_filter, mode)

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
    filters = norm_filters(filters, ['vpcs', 'subnets'], ['instances'], [])
    vpcs_filter = filters['vpcs']
    subnets_filter = filters['subnets']
    client = aws_client(resource_name = 'ec2', configuration = configuration, secrets = secrets)

    # rollback simulation gracefully
    logger.info(f'Unpartitioning VPCs matching {vpcs_filter} in zone {zone} ({mode}).')
    for vpc in client.describe_vpcs(Filters = vpcs_filter)['Vpcs']:
        unblock_vpc(client, zone, vpc['VpcId'], subnets_filter)

def block_vpc(client, zone, vpc_id, subnets_filter, mode):
    # get subnets in given zone for given VPC
    subnets_filter_amended = subnets_filter + [
        {'Name': 'availabilityZone', 'Values': [zone]},
        {'Name': 'vpc-id',           'Values': [vpc_id]}]
    subnets = client.describe_subnets(Filters = subnets_filter_amended)['Subnets']
    subnet_ids = [subnet['SubnetId'] for subnet in subnets]

    # get ACLs and their associations to the above subnets
    acls_filter = [
        {'Name': 'association.subnet-id', 'Values': subnet_ids}]
    acls = client.describe_network_acls(Filters = acls_filter)['NetworkAcls']
    assocs = [assoc for acl in acls for assoc in acl['Associations'] if assoc['SubnetId'] in subnet_ids]

    # create blocking ACL
    tags = [{
        'ResourceType': 'network-acl',
        'Tags': [
            {'Key': ZONE_TAG_NAME_LAMBDA(zone, subnets_filter), 'Value': '1'},
            {'Key': ORIGINAL_NETWORK_ACL_ASSOCIATIONS_TAG_NAME, 'Value': ';'.join([assoc['SubnetId'] + ':' + assoc['NetworkAclId'] for assoc in assocs])}]}]
    blocking_acl = client.create_network_acl(VpcId = vpc_id, TagSpecifications = tags)['NetworkAcl']
    blocking_acl_id = blocking_acl['NetworkAclId']
    modes = ['ingress', 'egress'] if mode == 'total' else [mode]
    for mode in ['ingress', 'egress']:
        client.create_network_acl_entry(
            CidrBlock    = '0.0.0.0/0',
            Egress       = mode == 'egress',
            NetworkAclId = blocking_acl_id,
            PortRange    = {'From': 0, 'To': 65535},
            Protocol     = '-1',
            RuleAction   = 'deny' if mode in modes else 'allow',
            RuleNumber   = 1) # lowest possible rank
    logger.info(f'Created blocking network access control list {blocking_acl_id}.')

    # associate above subnets with blocking ACL
    for assoc in assocs:
        assoc_id = assoc['NetworkAclAssociationId']
        subnet_id = assoc['SubnetId']
        # original_acl_id = assoc['NetworkAclId']
        client.replace_network_acl_association(AssociationId = assoc_id, NetworkAclId = blocking_acl_id)
        logger.info(f'Associated {subnet_id} (formerly via {assoc_id}) with blocking network access control list.')

def unblock_vpc(client, zone, vpc_id, subnets_filter):
    # get blocking ACLs
    acls_filter = [
        {'Name': 'vpc-id',  'Values': [vpc_id]},
        {'Name': 'tag-key', 'Values': [ZONE_TAG_NAME_LAMBDA(zone, subnets_filter)]}]
    blocking_acls = [blocking_acl for blocking_acl in client.describe_network_acls(Filters = acls_filter)['NetworkAcls']]

    # reassociate blocked subnets with original ACLs and then delete blocking ACLs
    for blocking_acl in blocking_acls:
        tag = [tag['Value'] for tag in blocking_acl['Tags'] if tag['Key'] == ORIGINAL_NETWORK_ACL_ASSOCIATIONS_TAG_NAME][0]
        subnet_id_to_original_acl_id = {subnet_id: original_acl_id for subnet_id, original_acl_id in [original_assoc.split(':') for original_assoc in tag.split(';')]}
        for assoc in blocking_acl['Associations']:
            assoc_id = assoc['NetworkAclAssociationId']
            subnet_id = assoc['SubnetId']
            blocking_acl_id = assoc['NetworkAclId']
            original_acl_id = subnet_id_to_original_acl_id[subnet_id]
            client.replace_network_acl_association(AssociationId = assoc_id, NetworkAclId = original_acl_id)
            logger.info(f'Reassociated {subnet_id} (formerly via {assoc_id}) with original network access control list.')
        blocking_acl_id = blocking_acl['NetworkAclId']
        client.delete_network_acl(NetworkAclId = blocking_acl_id)
        logger.info(f'Deleted blocking network access control list {blocking_acl_id}.')
