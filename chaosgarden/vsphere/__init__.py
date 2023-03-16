import ssl
from typing import Dict, List, Set

import requests
from chaoslib.types import Configuration, Secrets
from com.vmware import nsx_client, nsx_policy_client
from com.vmware.nsx_policy.infra import domains_client
from com.vmware.nsx_policy.model_client import (Condition, ConjunctionOperator,
                                                ExternalIDExpression, Group,
                                                GroupListResult,
                                                NestedExpression, Rule,
                                                SecurityPolicy,
                                                SecurityPolicyListResult)
from com.vmware.vapi.std.errors_client import NotFound
from com.vmware.vcenter import vm_client
from com.vmware.vcenter_client import VM
from logzero import logger
from pyVim.connect import SmartConnect
from pyVmomi import vim
from vmware.vapi.bindings.struct import VapiStruct
from vmware.vapi.bindings.stub import ApiClient
from vmware.vapi.lib import connect
from vmware.vapi.security.user_password import \
    create_user_password_security_context
from vmware.vapi.stdlib.client.factories import (StubConfiguration,
                                                 StubConfigurationFactory)
from vmware.vapi.vsphere.client import VsphereClient, create_vsphere_client

from chaosgarden.vsphere import pchelper


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
    if 'vsphere_username' not in secrets or 'vsphere_password' not in secrets:
        raise ValueError(f'Secrets with keys ' + ', '.join(secrets.keys()) + ' unknown/not supported!')
    username = secrets['vsphere_username']
    password = secrets['vsphere_password']
    if not 'vsphere_vcenter_server' in configuration:
        raise ValueError(f'Configuration with keys ' + ', '.join(configuration.keys()) + ' unknown/not supported!')
    server = configuration['vsphere_vcenter_server']
    skip_verification = configuration.get('vsphere_vcenter_insecure')
    session = get_unverified_session() if skip_verification else None
    return create_vsphere_client(server=server, username=username, password=password, session=session)

def vsphere_vcenter_service_instance(configuration: Configuration, secrets: Secrets)-> vim.ServiceInstance:
    """
    Get service instance client to vCenter SOAP API
    """
    if 'vsphere_username' not in secrets or 'vsphere_password' not in secrets:
        raise ValueError(f'Secrets with keys ' + ', '.join(secrets.keys()) + ' unknown/not supported!')
    username = secrets['vsphere_username']
    password = secrets['vsphere_password']
    if not 'vsphere_vcenter_server' in configuration:
        raise ValueError(f'Configuration with keys ' + ', '.join(configuration.keys()) + 'unknown/not supported!')
    server = configuration['vsphere_vcenter_server']
    skip_verification = configuration.get('vsphere_vcenter_insecure')
    return SmartConnect(host=server,user=username,pwd=password,disableSslCertValidation=skip_verification)

def validate_virtual_machines_filter(virtual_machines_filter: Dict[str,str]):
    expected_keys = ['custom_attributes', 'resource_pools', 'clusters']
    for key in expected_keys:
        if not key in virtual_machines_filter:
            raise ValueError(f'Missing key {key} in virtual machines filter')

class VirtualMachineCopy:
    def __init__(self, vm: vim.VirtualMachine):
        self.name = vm.name
        self.instanceUuid = vm.config.instanceUuid
        self.powerState = vm.runtime.powerState
        self.bootTime = vm.runtime.bootTime
        self._moId = vm._moId

    def __repr__(self):
        return f'VirtualMachine({self._moId},{self.name},{self.instanceUuid})'

def list_instances_copy(si: vim.ServiceInstance, zone: str, filter: Dict[str, any])->List[VirtualMachineCopy]:
    """
    Retrieve list with static fields (without potential subsequent SOAP calls)
    """
    results = []
    for vm in list_instances(si, zone, filter):
        try:
            copy = VirtualMachineCopy(vm)
            results.append(copy)
        except Exception as e:
            logger.debug(f'retrieving VirtualMachine details failed: {e}')
            pass
    return results

def list_instances(si: vim.ServiceInstance, zone: str, filter: Dict[str, any])->List[vim.VirtualMachine]:
    zone_resource_pools = [name.format(zone=zone) for name in filter['resource_pools']]
    pools = pchelper.search_resource_pools_by_names(si, zone_resource_pools)
    zone_clusters = [name.format(zone=zone) for name in filter['clusters']]
    clusters = pchelper.search_clusters_by_names(si, zone_clusters)
    if len(pools) == 0 and len(clusters) == 0:
        raise ValueError(f'no resource pools {zone_resource_pools} and no clusters {zone_clusters} found')

    custom_attrs = {}
    for keyname, value in filter['custom_attributes'].items():
        found = False
        for fieldDef in si.content.customFieldsManager.field:
            if fieldDef.name == keyname:
                custom_attrs[fieldDef.key] = value
                found = True
                break
        if not found:
            raise ValueError(f'custom field def {keyname} not found')

    for cluster in clusters:
        pools.append(cluster.resourcePool)

    pools = _include_child_pools(pools)

    def matches_custom_attrs(vm: vim.VirtualMachine) -> bool:
        for key, value in custom_attrs.items():
            found = False
            for cv in vm.customValue:
                if cv.key == key:
                    if cv.value != value:
                        return False
                    found = True
                    break
            if not found:
                return False
        return True

    vms = []
    for pool in pools:
        for vm in pool.vm:
            if matches_custom_attrs(vm):
                vms.append(vm)
    return vms

def _include_child_pools(pools):
    result = pools[:]
    for pool in pools:
        result += _include_child_pools(pool.resourcePool)
    return result

def delete_instances(client: VsphereClient, vms: List[vim.VirtualMachine]):
    for vm in vms:
        logger.info(f'stopping VM {vm.name}')
        client.vcenter.vm.Power.stop(vm._moId)
        logger.info(f'deleting VM {vm.name}')
        client.vcenter.VM.delete(vm._moId)

def reset_instances(client: VsphereClient, vms: List[vim.VirtualMachine]):
    for vm in vms:
        logger.info(f'resetting VM {vm.name}')
        client.vcenter.vm.Power.reset(vm._moId)

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
    if 'nsxt_username' not in secrets or 'nsxt_password' not in secrets:
        raise ValueError(f'Secrets with keys ' + ', '.join(secrets.keys()) + ' unknown/not supported!')
    username = secrets['nsxt_username']
    password = secrets['nsxt_password']
    if not 'vsphere_nsxt_server' in configuration:
        raise ValueError(f'Configuration with keys ' + ', '.join(configuration.keys()) + 'unknown/not supported!')
    server = configuration['vsphere_nsxt_server']
    skip_verification = configuration.get('vsphere_nsxt_insecure')
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

def nsxt_build_expression_vm_uuids(vm_uuids: List[str])->VapiStruct:
    """
    Create filter expressions by virtual machine UUIDs
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

def nsxt_get_security_policy(client: ApiClient, policy_id: str)->SecurityPolicy:
    try:
        return client.infra.domains.SecurityPolicies.get(domain_id="default",security_policy_id=policy_id)
    except NotFound:
        return None

def nsxt_create_security_policy(client: ApiClient, policy_id: str, policy: SecurityPolicy):
    #domains_client.SecurityPolicies.patch
    client.infra.domains.SecurityPolicies.patch(domain_id="default", security_policy_id=policy_id, security_policy=policy)

def nsxt_build_security_policy(group_id: str, add_ingress_rule: bool = True, add_egress_rule: bool = True)->SecurityPolicy:
    any = ['ANY']
    target = [f'/infra/domains/default/groups/{group_id}']
    rules = []
    if add_ingress_rule:
        rules.append(Rule(
            id="block-ingress",
            source_groups=any,
            destination_groups=target,
            action=Rule.ACTION_DROP,
            direction=Rule.DIRECTION_IN_OUT,
            profiles=any,
            services=any,
            scope=any))
    if add_egress_rule:
        rules.append(Rule(
            id="block-egress",
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