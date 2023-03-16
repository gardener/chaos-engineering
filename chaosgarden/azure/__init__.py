import time

from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.resourcegraph.models import (QueryRequest, QueryRequestOptions,
                                             ResultFormat)
from box import Box
from chaosazure import (init_compute_management_client,
                        init_resource_graph_client)
from chaosazure.auth import auth
from chaosazure.common.config import load_configuration, load_secrets
from chaoslib.types import Configuration, Secrets
from logzero import logger


class AzureClient():
    def __init__(self, configuration, secrets):
        self.subscription_id = configuration['azure_subscription_id']
        self.resourcegraph   = init_resource_graph_client(experiment_secrets = secrets)
        self.compute         = init_compute_management_client(experiment_secrets = secrets, experiment_configuration = configuration)
        self.network         = AzureClient._init_network_management_client(experiment_secrets = secrets, experiment_configuration = configuration)

    # missing network client initialization in upstream chaosazure implementation
    @staticmethod
    def _init_network_management_client(
            experiment_secrets: Secrets,
            experiment_configuration: Configuration) -> NetworkManagementClient:
        # adapted from compute client to network client from https://github.com/chaostoolkit-incubator/chaostoolkit-azure/blob/master/chaosazure/__init__.py#L43-L61
        secrets = load_secrets(experiment_secrets)
        configuration = load_configuration(experiment_configuration)
        with auth(secrets) as authentication:
            base_url = secrets.get('cloud').endpoints.resource_manager
            scopes = [base_url + '/.default']
            client = NetworkManagementClient(
                credential        = authentication,
                credential_scopes = scopes,
                subscription_id   = configuration.get('subscription_id'),
                base_url          = base_url)
            return client


def azure_client(configuration, secrets):
    return AzureClient(configuration, secrets)

def list_vms(client, resource_group, zone, filter):
    # https://learn.microsoft.com/en-us/python/api/azure-mgmt-resourcegraph/azure.mgmt.resourcegraph.operations.resourcegraphclientoperationsmixin?view=azure-python
    # query syntax:
    # - https://learn.microsoft.com/en-us/azure/data-explorer/kusto/query/
    # - https://learn.microsoft.com/de-de/azure/data-explorer/kusto/query/equals-cs-operator
    # - https://learn.microsoft.com/de-de/azure/data-explorer/kusto/query/contains-operator
    # note that the `chaosazure` implementation seemed rather wasteful as it recreates the client with every request,
    # so it seemed more appropriate to create the client only once and implement our own custom resource query, see also:
    # - https://github.com/chaostoolkit-incubator/chaostoolkit-azure/blob/664ac995e1c13eb564d7daa491bf6fdfaa2df8c3/chaosazure/__init__.py#L127 ->
    # - https://github.com/chaostoolkit-incubator/chaostoolkit-azure/blob/master/chaosazure/common/resources/graph.py#L13
    query = f'resources | where type == "microsoft.compute/virtualmachines" | where resourceGroup == "{resource_group}" | where zones contains "{zone}"'
    if filter:
        query += f' | {filter}'
    response = client.resourcegraph.resources(QueryRequest(
        query         = query,
        subscriptions = [client.subscription_id],
        options       = QueryRequestOptions(result_format = ResultFormat.object_array)))
    vms = []
    for resource in response.data:
        vms.append(Box(resource))
    return vms

def list_nics(client, resource_group):
    # https://learn.microsoft.com/en-us/python/api/azure-mgmt-network/azure.mgmt.network.v2022_05_01.operations.networkinterfacesoperations?view=azure-python#azure-mgmt-network-v2022-05-01-operations-networkinterfacesoperations-list
    nics = []
    for nic in client.network.network_interfaces.list(resource_group_name = resource_group):
        nics.append(nic)
    return nics

def list_nsgs(client, resource_group):
    # https://learn.microsoft.com/en-us/python/api/azure-mgmt-network/azure.mgmt.network.v2022_05_01.operations.networksecuritygroupsoperations?view=azure-python#azure-mgmt-network-v2022-05-01-operations-networksecuritygroupsoperations-list
    nsgs = []
    for nsg in client.network.network_security_groups.list(resource_group_name = resource_group):
        nsgs.append(nsg)
    return nsgs

def delete_vm(client, resource_group, zone, vm_name):
    # https://learn.microsoft.com/en-us/python/api/azure-mgmt-compute/azure.mgmt.compute.v2022_08_01.operations.virtualmachinesoperations?view=azure-python#azure-mgmt-compute-v2022-08-01-operations-virtualmachinesoperations-begin-delete
    logger.info(f'Deleting virtual machine {vm_name} in zone {zone}')
    return client.compute.virtual_machines.begin_delete(resource_group, vm_name)

def restart_vm(client, resource_group, zone, vm_name):
    # https://learn.microsoft.com/en-us/python/api/azure-mgmt-compute/azure.mgmt.compute.v2022_08_01.operations.virtualmachinesoperations?view=azure-python#azure-mgmt-compute-v2022-08-01-operations-virtualmachinesoperations-begin-restart
    logger.info(f'Restarting virtual machine {vm_name} in zone {zone}')
    return client.compute.virtual_machines.begin_restart(resource_group, vm_name)

def create_nsg(client, resource_group, nsg):
    # https://learn.microsoft.com/en-us/python/api/azure-mgmt-network/azure.mgmt.network.v2022_05_01.operations.networksecuritygroupsoperations?view=azure-python#azure-mgmt-network-v2022-05-01-operations-networksecuritygroupsoperations-begin-create-or-update
    logger.info(f'Creating nsg {nsg.name}')
    return client.network.network_security_groups.begin_create_or_update(resource_group, nsg.name, nsg)

def delete_nsg(client, resource_group, nsg_name):
    # https://learn.microsoft.com/en-us/python/api/azure-mgmt-network/azure.mgmt.network.v2022_05_01.operations.networksecuritygroupsoperations?view=azure-python#azure-mgmt-network-v2022-05-01-operations-networksecuritygroupsoperations-begin-delete
    logger.info(f'Deleting nsg {nsg_name}')
    return client.network.network_security_groups.begin_delete(resource_group_name = resource_group, network_security_group_name = nsg_name)

def update_nic(client, resource_group, nic):
    # https://learn.microsoft.com/en-us/python/api/azure-mgmt-network/azure.mgmt.network.v2022_05_01.operations.networkinterfacesoperations?view=azure-python#azure-mgmt-network-v2022-05-01-operations-networkinterfacesoperations-begin-create-or-update
    logger.info(f'Updating nic {nic.name}')
    return client.network.network_interfaces.begin_create_or_update(resource_group, nic.name, nic)

def wait_on_operations(operations):
    # https://learn.microsoft.com/en-us/python/api/azure-core/azure.core.polling.lropoller
    logger.debug(f'Waiting on {len(operations)} operations.')
    for operation in operations:
        wait_on_operation(operation)

def wait_on_operation(operation):
    # https://learn.microsoft.com/en-us/python/api/azure-core/azure.core.polling.lropoller
    logger.debug(f'Waiting on operation.')
    try:
        while not operation.done():
            time.sleep(1)
        logger.debug(f'Operation returned with status {operation.status()} and result: {operation.result()}')
        if operation.status().lower() == 'succeeded':
            return operation.result()
        else:
            raise RuntimeError(f'Operation returned with status {operation.status()} and result: {operation.result()}')
    except Exception as e:
        logger.error(f'Operation failed: {type(e)}: {e}')
