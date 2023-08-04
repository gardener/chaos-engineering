
import random
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta
from threading import Thread
from typing import Dict, List, Any, Tuple

from chaoslib.types import Configuration, Secrets
from logzero import logger

from chaosgarden.alicloud import (AliyunBot)

from chaosgarden.util import (norm_filters, validate_duration, validate_mode,
                              validate_zone)
from chaosgarden.util.terminator import Terminator
from chaosgarden.util.threading import launch_thread


ZONE_TAG_NAME = 'gardener.cloud/chaos/zone'
ACL_MODE_TAG_NAME = 'gardener.cloud/chaos/mode'
VPC_TAG_NAME = 'gardener.cloud/chaos/vpc'
ORIGINAL_NETWORK_ACL_ASSOCIATIONS_TAG_NAME = 'gardener.cloud/chaos/original-network-acl-associations'
ASSUMED_COMPUTE_TERMINATION_TIME_IN_SECONDS = 60
ASSUMED_COMPUTE_RESTART_TIME_IN_SECONDS = 90
REUSE_ACL = False

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
    filters = norm_filters(filters, ['instances', 'vpc'], [], [])
    
    vpc_filter = filters['vpc']
    instance_filter = filters['instances']
    vpc_name = vpc_filter['Name']
    instance_tag_key = instance_filter['Tag-key']

    alibot = AliyunBot(access_key=secrets['ali_access_key'], secret_key=secrets['ali_secret_key'], region=configuration['ali_region'])    
    logger.info(f'Validating alibot credentials and listing probably impacted instances and/or networks with the given arguments {zone=} and {filters=}:')
    
    instance_list, the_vpc = get_impact_instance_and_vpc(alibot, instance_tag_key, vpc_name, [zone])
    logger.info(f'{len(instance_list)} instance(s) would be impacted:')
    for instance in sorted(instance_list, key = lambda instance: instance["InstanceId"]):
        logger.info(f'- {instance["InstanceId"]}') 
    if the_vpc is None:
        logger.info(f'no VPC found')    
    else:
        logger.info('Follow VPC would be impacted:')
        logger.info(f'- {the_vpc["VpcId"]}')
        




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
    validate_zone(zone)
    filters = norm_filters(filters, ['instances', 'vpc'], [], [])
    
    vpc_filter = filters['vpc']
    instance_filter = filters['instances']
    vpc_name = vpc_filter['Name']
    instance_tag_key = instance_filter['Tag-key']

    alibot = AliyunBot(access_key=secrets['ali_access_key'], secret_key=secrets['ali_secret_key'], region=configuration['ali_region'])

    # distinguish modes
    if mode == 'terminate':
        operation = alibot.delete_instance
        reschedule_timedelta = timedelta(seconds = ASSUMED_COMPUTE_TERMINATION_TIME_IN_SECONDS) # back-off, in case termination fails silently
    if mode == 'restart':
        operation = alibot.reboot_instance
        reschedule_timedelta = timedelta(seconds = ASSUMED_COMPUTE_RESTART_TIME_IN_SECONDS + random.randint(min_runtime, max_runtime)) # next restart


    # mess up instances continuously until terminated
    logger.info(f'Messing up instances matching {instance_filter} in zone {zone} ({mode} between {min_runtime}s and {max_runtime}s).')
    schedule_by_id = {}
    terminator = Terminator(duration)
    while not terminator.is_terminated():
        try:
            instance_list, the_vpc = get_impact_instance_and_vpc(alibot, instance_tag_key, vpc_name, [zone])
            for instance in instance_list:
                instance_id = instance['InstanceId']
                if instance_id not in schedule_by_id:
                    schedule_by_id[instance_id] = datetime.now().astimezone() + timedelta(seconds = random.randint(min_runtime, max_runtime))
                    logger.info(f'Scheduled virtual machine to {mode}: {instance_id} at {schedule_by_id[instance_id]}')
                if datetime.now().astimezone() > schedule_by_id[instance_id]:
                    schedule_by_id[instance_id] = datetime.now().astimezone() + reschedule_timedelta
                    if not operation(InstId=instance_id):
                        logger.error(f'Virtual machine:{instance_id} failed to {mode} ')
                        schedule_by_id[instance_id] = datetime.now().astimezone() + timedelta(seconds = 1)
        except Exception as e:
            logger.error(f'Virtual machines failed to {mode}: {type(e)}: {e}')
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
    if not REUSE_ACL:
        rollback_network_failure_simulation(mode, zone, filters, configuration, secrets)

    # input validation
    validate_duration(duration)
    validate_mode(mode, ['total', 'ingress', 'egress'])
    validate_zone(zone)
    filters = norm_filters(filters, ['instances', 'vpc'], [], [])
    vpc_filter = filters['vpc']
    instance_filter = filters['instances']
    vpc_name = vpc_filter['Name']
    instance_tag_key = instance_filter['Tag-key']

    alibot = AliyunBot(access_key=secrets['ali_access_key'], secret_key=secrets['ali_secret_key'], region=configuration['ali_region'])

    

    # block network traffic
    logger.info(f'Partitioning VPCs matching {vpc_filter} in zone {zone} ({mode}).')
    instance_list, the_vpc = get_impact_instance_and_vpc(alibot, instance_tag_key, vpc_name, [zone])
    if the_vpc:
        block_vpc(alibot, [zone], the_vpc['VpcId'], mode)

    # wait until terminated
    terminator = Terminator(duration)
    while not terminator.is_terminated():
        time.sleep(1)

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
    validate_zone(zone)
    filters = norm_filters(filters, ['instances', 'vpc'], [], [])
    vpc_filter = filters['vpc']
    instance_filter = filters['instances']
    vpc_name = vpc_filter['Name']
    instance_tag_key = instance_filter['Tag-key']

    alibot = AliyunBot(access_key=secrets['ali_access_key'], secret_key=secrets['ali_secret_key'], region=configuration['ali_region'])

    # rollback simulation gracefully
    logger.info(f'Unpartitioning VPCs matching {vpc_filter} in zone {zone} ({mode}).')
    instance_list, the_vpc = get_impact_instance_and_vpc(alibot, instance_tag_key, vpc_name, [zone])
    if the_vpc:
        unblock_vpc(alibot, [zone], the_vpc['VpcId'], mode)
    else:
        logger.info(f'No Vpc found named with {vpc_name}')


###########
# Helpers #
###########

def list_instances_by_tagkey_and_zone(
    alibot: AliyunBot, 
    tag_list: List[ Dict[ str, str ]], 
    zone_list: List[ str ]) -> List[ Any ]:

    the_list, err = alibot.list_instance_with_tag(tag_list=tag_list)
    if err or the_list is None:
        return []

    return [ ins for ins in the_list if ins['ZoneId'] in zone_list ]

def get_impact_instance_and_vpc(
    alibot: AliyunBot, 
    instance_tag_key: str,
    vpc_name: str, 
    zone_list: List[ str ]) -> Tuple[ List[ Any ], Any ]:
            
    filter_tag_list = [
        {
            'Key': instance_tag_key,
            'Value': None
        }
    ]
    instance_list = list_instances_by_tagkey_and_zone(alibot, filter_tag_list, zone_list)
    instance_vpc_id = instance_list[0]['VpcId'] if len(instance_list) > 0 else None
    the_vpc, err = alibot.get_vpc(VpcName=vpc_name, VpcId=instance_vpc_id)
    return instance_list, the_vpc


def get_network_acl_by_tag_and_vpc(
    alibot: AliyunBot, 
    tag_list: List[ Dict[ str, str ]], 
    vpc_id: str) -> Any:

    the_list, err = alibot.list_network_acl_with_tag(tag_list)
    if err or the_list is None:
        return None
    for acl in the_list:
        if acl['VpcId'] == vpc_id:
            return acl
    return None

def get_or_create_block_acl(
    alibot: AliyunBot, 
    vpc_id: str, 
    mode: str, 
    create_if_not_exists: bool=False) -> Any:

    acl_tag_list = [
        {
            'Key': ACL_MODE_TAG_NAME,
            'Value': mode
        },
        {
            'Key': VPC_TAG_NAME,
            'Value': vpc_id
        },
    ]
    block_acl = get_network_acl_by_tag_and_vpc(alibot, acl_tag_list, vpc_id)
    if not block_acl and create_if_not_exists:
        block_acl_id, err = alibot.create_network_acl(VpcId=vpc_id, AclName=f'block_acl_{mode}_for_{vpc_id}')
        if err:
            logger.warning(f'Created network acl failed, can not block vpc.')
            if block_acl_id:
                alibot.delete_network_acl(AclId=block_acl_id)
            return None

        EgressAclEntry = {
            'DestinationCidrIp':   '0.0.0.0/0',
            'Policy':   'drop',  # 'accept' 'drop'
            'Port':     '-1/-1', # '1/200' '80/80'
            'Protocol': 'all',  # 'all' 'icmp' 'gre' 'tcp' 'udp' 
        }
        IngressAclEntry = {
            'SourceCidrIp':   '0.0.0.0/0',
            'Policy':   'drop',  # 'accept' 'drop'
            'Port':     '-1/-1', # '1/200' '80/80'
            'Protocol': 'all',  # 'all' 'icmp' 'gre' 'tcp' 'udp' 
        }
        EgressAclEntry_list=[]
        IngressAclEntry_list=[]
        if mode in ['total', 'egress']:
            EgressAclEntry_list = [EgressAclEntry]
        if mode in ['total', 'ingress']:
            IngressAclEntry_list = [IngressAclEntry]

        if not alibot.update_network_acl_entries(AclId=block_acl_id, EgressAclEntry_list=EgressAclEntry_list, IngressAclEntry_list=IngressAclEntry_list):
            logger.warning(f'Update Network Acl Entries failed, can not block vpc.')
            alibot.delete_network_acl(AclId=block_acl_id)
            return None
        logger.info(f'Created network acl {block_acl_id}.')
        if not alibot.tag_network_acl(block_acl_id, acl_tag_list):
            logger.warning(f'tag network acl failed !')
            alibot.delete_network_acl(AclId=block_acl_id)
            return None
        block_acl, err = alibot.get_network_acl(AclId=block_acl_id)
    
    return block_acl


def block_vpc(
    alibot: AliyunBot, 
    zone_list: List[str], 
    vpc_id: str, 
    mode: str):

    logger.info(f'begin to block vpc {vpc_id} ')
    # find wxist blocking ACL
    block_acl = get_or_create_block_acl(alibot, vpc_id, mode, create_if_not_exists=True)
    if block_acl is None:
        logger.warning(f'can not get or create alc for mode {mode} in vpc {vpc_id}, block vp failed.')
        return

    block_acl_id = block_acl['NetworkAclId']
    assocs_str = block_acl['Tags'].get(ORIGINAL_NETWORK_ACL_ASSOCIATIONS_TAG_NAME)
    assocs_map = json.loads(assocs_str) if assocs_str else {}

    # get vswitches in given zone for given VPC
    vswitch_list = []
    for zone in zone_list:
        zone_vswitch_list, err = alibot.list_vswitches(VpcId=vpc_id, ZoneId=zone)
        if zone_vswitch_list:
            vswitch_list.extend(zone_vswitch_list)
    
    need_op_vswitch_list = []
    for vswitch in vswitch_list:
        vswitch_id = vswitch["VSwitchId"]
        assoc_acl = vswitch["NetworkAclId"]
        if assoc_acl != block_acl_id:
            need_op_vswitch_list.append(vswitch)
            assocs_map.update(
                {
                    f'{vswitch["VSwitchId"]}': f'{vswitch["NetworkAclId"]}'
                }
            )
    
    new_assocs_str = json.dumps(assocs_map)

    # tag block_acl

    acl_tag_list = [
        {
            'Key': ORIGINAL_NETWORK_ACL_ASSOCIATIONS_TAG_NAME,
            'Value': new_assocs_str
        }
    ]
    if not alibot.tag_network_acl(block_acl_id, acl_tag_list):
        logger.warning(f'tag network acl failed !')
        return

    # bind block acl to vswitch
    for vswitch in need_op_vswitch_list:
        vswitch_id = vswitch["VSwitchId"]
        if not alibot.replace_vswitch_acl_bind(VSwitchId=vswitch_id, AclId=block_acl_id):
            logger.warning(f'bind block acl {block_acl_id} to vswitch {vswitch_id} failed !')
        else:
            logger.info(f'bind block acl {block_acl_id} to vswitch {vswitch_id} successfully !')


    logger.info(f'All vswitches are binded to the block acl {block_acl_id}, block vpc {vpc_id} completed! ')

def unblock_vpc(
    alibot: AliyunBot, 
    zone_list: List[str], 
    vpc_id: str, 
    mode: str):

    logger.info(f'begin to unblock vpc {vpc_id} ')

    # get blocking ACL
    exists_block_acl = get_or_create_block_acl(alibot, vpc_id, mode)
    if exists_block_acl is None:
        clean_up_acl(alibot, vpc_id, mode)
        logger.info(f'unable find exists alc for mode {mode} in vpc {vpc_id}, unblock exited!!')
        return

    blocking_acl_id = exists_block_acl['NetworkAclId']
    logger.info(f'got exists block acl {blocking_acl_id}')


    assocs_str = exists_block_acl['Tags'].get(ORIGINAL_NETWORK_ACL_ASSOCIATIONS_TAG_NAME)
    assocs_map = json.loads(assocs_str) if assocs_str else {}

    # get vswitches in given zone for given VPC
    vswitch_list = []
    for zone in zone_list:
        zone_vswitch_list, err = alibot.list_vswitches(VpcId=vpc_id, ZoneId=zone)
        if zone_vswitch_list:
            vswitch_list.extend(zone_vswitch_list)
    
    for vswitch in vswitch_list:
        vswitch_id = vswitch["VSwitchId"]
        assoc_acl = vswitch["NetworkAclId"]
        if assoc_acl == blocking_acl_id:
            # original_acl_id = assocs_map.pop(vswitch_id, None)
            original_acl_id = assocs_map.get(vswitch_id)
            if original_acl_id:
                if not alibot.replace_vswitch_acl_bind(VSwitchId=vswitch_id, AclId=original_acl_id):
                    logger.warning(f'Reassociated {vswitch_id}  with original network acl {original_acl_id} failed!!')
                else:
                    assocs_map.pop(vswitch_id, None)
                    logger.info(f'Reassociated {vswitch_id}  with original network acl {original_acl_id} successfully.')


    new_assocs_str = json.dumps(assocs_map)

    # tag block_acl

    acl_tag_list = [
        {
            'Key': ORIGINAL_NETWORK_ACL_ASSOCIATIONS_TAG_NAME,
            'Value': new_assocs_str
        }
    ]
    if not alibot.tag_network_acl(blocking_acl_id, acl_tag_list):
        logger.warning(f'tag network acl failed !')
    
    # delete block acl
    clean_up_acl(alibot, vpc_id, mode)
    
    logger.info(f'unblock {vpc_id} completed! ')
    
def clean_up_acl(
    alibot: AliyunBot, 
    vpc_id: str, 
    mode: str):
    AclName=f'block_acl_{mode}_for_{vpc_id}'
    acl_list, err = alibot.list_network_acl_by_name(AclName)
    if err is None:
        for the_acl in acl_list:
            if not REUSE_ACL or len(the_acl['Tags']) == 0:
                acl_id = the_acl['NetworkAclId']
                alibot.delete_network_acl(AclId=acl_id)
                logger.info(f'acl {acl_id} deleted.')
