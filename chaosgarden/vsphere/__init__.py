import ssl
import requests
from typing import Set, List, Dict

from chaoslib.types import Configuration, Secrets
from logzero import logger
from chaosgarden.vsphere import pchelper

from vmware.vapi.vsphere.client import create_vsphere_client, VsphereClient
from com.vmware.vcenter_client import VM
from pyVmomi import vim
from pyVim.connect import SmartConnect
from vmware.vapi.lib import connect
from vmware.vapi.security.user_password import create_user_password_security_context
from vmware.vapi.stdlib.client.factories import StubConfigurationFactory, StubConfiguration
from com.vmware import nsx_policy_client
from com.vmware import nsx_client
from vmware.vapi.bindings.stub import ApiClient
from com.vmware.nsx_policy.infra import domains_client
from com.vmware.nsx_policy.model_client import (Group,GroupListResult,Condition,ConjunctionOperator,
                                                NestedExpression,ExternalIDExpression,
                                                SecurityPolicy,SecurityPolicyListResult,Rule)
from vmware.vapi.bindings.struct import VapiStruct

def get_unverified_context():
    """
    Get an unverified ssl context. Used to disable the server certificate
    verification.
    @return: unverified ssl context.
    """
    context = None
    if hasattr(ssl, '_create_unverified_context'):
        context = ssl._create_unverified_context()
    return context

def get_unverified_session():
    """
    Get a requests session with cert verification disabled.
    Also disable the insecure warnings message.
    Note this is not recommended in production code.
    @return: a requests session with verification disabled.
    """
    session = requests.session()
    session.verify = False
    requests.packages.urllib3.disable_warnings()
    return session

def vsphere_vcenter_client(configuration: Configuration, secrets: Secrets)-> VsphereClient:
    """
    Get client to vCenter REST API
    """
    if not 'cloud_provider' in secrets:
        raise ValueError(f'Secrets with keys ' + ', '.join(secrets.keys()) + 'unknown/not supported!')
    secret = secrets['cloud_provider']
    if not 'vsphereUsername' in secret or not 'vspherePassword' in secret:
        raise ValueError(f'Secrets with keys ' + ', '.join(secrets.keys()) + 'unknown/not supported!')
    username = secret['vsphereUsername']
    password = secret['vspherePassword']
    if not 'vsphere_vcenter_server' in configuration:
        raise ValueError(f'Configuration with keys ' + ', '.join(configuration.keys()) + 'unknown/not supported!')
    server = configuration['vsphere_vcenter_server']
    skip_verification = 'vsphere_insecure' in configuration and configuration['vsphere_insecure']
    session = get_unverified_session() if skip_verification else None
    return create_vsphere_client(server=server, username=username, password=password, session=session)

def vsphere_vcenter_service_instance(configuration: Configuration, secrets: Secrets)-> vim.ServiceInstance:
    """
    Get service instance client to vCenter SOAP API
    """
    if not 'cloud_provider' in secrets:
        raise ValueError(f'Secrets with keys ' + ', '.join(secrets.keys()) + 'unknown/not supported!')
    secret = secrets['cloud_provider']
    if not 'vsphereUsername' in secret or not 'vspherePassword' in secret:
        raise ValueError(f'Secrets with keys ' + ', '.join(secrets.keys()) + 'unknown/not supported!')
    username = secret['vsphereUsername']
    password = secret['vspherePassword']
    if not 'vsphere_vcenter_server' in configuration:
        raise ValueError(f'Configuration with keys ' + ', '.join(configuration.keys()) + 'unknown/not supported!')
    server = configuration['vsphere_vcenter_server']
    skip_verification = 'vsphere_insecure' in configuration and configuration['vsphere_insecure']
    return SmartConnect(host=server,user=username,pwd=password,disableSslCertValidation=skip_verification)

def list_instances(client: VsphereClient, zone: str, resource_pool_prefix: str, shoot_technical_id: str):
    zone_resource_pool_name = f'{resource_pool_prefix}-{zone}'
    resource_pool = get_resource_pool(client, zone_resource_pool_name)
    if not resource_pool:
        raise ValueError(f'resource pool {zone_resource_pool_name} not found')
    prefix = f'{shoot_technical_id}-'
    vms = client.vcenter.VM.list(VM.FilterSpec(resource_pools=set([resource_pool.resource_pool])))
    return [vm for vm in vms if vm.name.startswith(prefix)]

def stop_instances(client: VsphereClient, vms: list):
    for vm in vms:
        logger.info(f'stopping VM {vm.name}')
        client.vcenter.vm.Power.stop(vm.vm)

def start_instances(client: VsphereClient, vms: list):
    for vm in vms:
        logger.info(f'starting VM {vm.name}')
        client.vcenter.vm.Power.start(vm.vm)

def get_resource_pool(client: VsphereClient, name: str)-> str:
    pools = client.vcenter.ResourcePool.list()
    for pool in pools:
        if pool.name == name:
            return pool
    return None

def get_virtualmachines(service_instance: vim.ServiceInstance, vm_name_set: Set[str])->Dict[str, vim.VirtualMachine]:
    """
    Get VirtualMachine object (including VirtualMachineRuntimeInfo) via SOAP client
    """
    result = {}
    for vm in pchelper.search_vms_by_names(service_instance, vm_name_set):
        result[vm.name] = vm
    return result

def vsphere_nsxt_client(configuration: Configuration, secrets: Secrets, is_policy = False)-> ApiClient:
    """
    Get client to NSX-T policy REST API
    """
    if not 'cloud_provider' in secrets:
        raise ValueError(f'Secrets with keys ' + ', '.join(secrets.keys()) + 'unknown/not supported!')
    secret = secrets['cloud_provider']
    if not 'nsxtUsername' in secret or not 'nsxtUsername' in secret:
        raise ValueError(f'Secrets with keys ' + ', '.join(secrets.keys()) + 'unknown/not supported!')
    username = secret['nsxtUsername']
    password = secret['nsxtPassword']
    if not 'vsphere_nsxt_server' in configuration:
        raise ValueError(f'Configuration with keys ' + ', '.join(configuration.keys()) + 'unknown/not supported!')
    server = configuration['vsphere_nsxt_server']
    skip_verification = 'vsphere_insecure' in configuration and configuration['vsphere_insecure']
    session = get_unverified_session() if skip_verification else requests.session()
    nsx_url = f'https://{server}:443'
    connector = connect.get_requests_connector(session=session, msg_protocol='rest', url=nsx_url)
    stub_config = StubConfigurationFactory.new_std_configuration(connector)
    security_context = create_user_password_security_context(username, password)
    connector.set_security_context(security_context)
    if is_policy:
        stub_factory = nsx_policy_client.StubFactory(stub_config)
    else:
        stub_factory = nsx_client.StubFactory(stub_config)
    return ApiClient(stub_factory)

def nsxt_list_infra_domain_groups(client: ApiClient)->GroupListResult:
    #domains_client.Groups.list(domain_id="default")
    return client.infra.domains.Groups.list(domain_id="default")

def nsxt_create_infra_domain_group(client: ApiClient, group_id: str, expression: List[VapiStruct]):
    group = Group(
        display_name=group_id,
        description="created by chaosgarden",
        expression=expression,
    )
    client.infra.domains.Groups.patch(domain_id="default", group_id=group_id, group=group)

def nsxt_build_expression_shoot_vm_name_filter(shoot_technical_id: str, zone_technical_id: str)->VapiStruct:
    """
    Create filter expression based on shoot_technical_id and zone_technical_id (e.g. like 'z1')
    """
    name_condition = Condition(
        member_type=Condition.MEMBER_TYPE_VIRTUALMACHINE,
        key=Condition.KEY_COMPUTERNAME,
        operator=Condition.OPERATOR_STARTSWITH,
        value=f'{shoot_technical_id}-',
    )
    zone_name_condition = Condition(
        member_type=Condition.MEMBER_TYPE_VIRTUALMACHINE,
        key=Condition.KEY_COMPUTERNAME,
        operator=Condition.OPERATOR_CONTAINS,
        value=f'-{zone_technical_id}-',
    )
    conj = ConjunctionOperator(
        conjunction_operator=ConjunctionOperator.CONJUNCTION_OPERATOR_AND,
    )
    return NestedExpression(
        expressions=[name_condition,conj,zone_name_condition]
    )

def nsxt_build_expression_vm_uuids(vm_uuids: List[str])->VapiStruct:
    """
    Create filter expresions by virtual machine UUIDs
    """
    return ExternalIDExpression(
        external_ids=vm_uuids,
        member_type=ExternalIDExpression.MEMBER_TYPE_VIRTUALMACHINE,
    )

def nsxt_delete_infra_domain_group(client: ApiClient, group_id: str, force: bool = False):
    client.infra.domains.Groups.delete(domain_id="default", group_id=group_id, fail_if_subtree_exists=False, force=force)

def nsxt_list_security_policies(client: ApiClient)->SecurityPolicyListResult:
    #domains_client.SecurityPolicies.list()
    return client.infra.domains.SecurityPolicies.list(domain_id="default")

def nsxt_get_security_policies(client: ApiClient, policy_id: str)->SecurityPolicy:
    return client.infra.domains.SecurityPolicies.get(domain_id="default",security_policy_id=policy_id)

def nsxt_create_security_policy(client: ApiClient, policy_id: str, policy: SecurityPolicy):
    #domains_client.SecurityPolicies.patch
    client.infra.domains.SecurityPolicies.patch(domain_id="default", security_policy_id=policy_id, security_policy=policy)

def nsxt_build_security_policy(group_id: str, add_ingress_rule: bool = True, add_egress_rule: bool = True)->SecurityPolicy:
    any = ['ANY']
    target = [f'/infra/domains/default/groups/{group_id}']
    rules = []
    if add_ingress_rule:
        rules.append(Rule(
            id="ingress",
            source_groups=any,
            destination_groups=target,
            action=Rule.ACTION_DROP,
            direction=Rule.DIRECTION_IN_OUT,
            profiles=any,
            services=any,
            scope=any))
    if add_egress_rule:
        rules.append(Rule(
            id="egress",
            source_groups=target,
            destination_groups=any,
            action=Rule.ACTION_DROP,
            direction=Rule.DIRECTION_IN_OUT,
            profiles=any,
            services=any,
            scope=any))
    return SecurityPolicy(
        description="created by chaosgarden",
        scope=target,
        rules=rules
    )

def nsxt_delete_security_policy(client: ApiClient, policy_id: str):
    client.infra.domains.SecurityPolicies.delete(domain_id="default", security_policy_id=policy_id)