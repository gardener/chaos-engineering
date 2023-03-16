import json
import time
from uuid import uuid4

from box import Box
from chaoslib.types import Secrets
from logzero import logger


def project_id_from_secrets(secrets: Secrets):
    if 'service_account_info' in secrets:
        return secrets['service_account_info']['project_id']
    elif 'service_account_file' in secrets:
        with open(secrets['service_account_file'], 'rt') as file:
            secrets = json.load(file)
        return secrets['project_id']
    else:
        raise ValueError(f'Secrets with keys ' + ', '.join(secrets.keys()) + 'unknown/not supported!')

def list_instances(client, project, zone, filter):
    # https://cloud.google.com/compute/docs/reference/rest/v1/instances/list
    request = client.instances().list(project = project, zone = zone, filter = filter) # tags such as `tags.items=kubernetes-io-cluster-shoot--core--chaos-gcp-3z` do not work, see https://issuetracker.google.com/issues/120255780#comment14
    instances = []
    while request:
        response = request.execute()
        if 'items' in response:
            for item in response['items']:
                instances.append(Box(item))
        request = client.instances().list_next(previous_request = request, previous_response = response)
    return instances

def list_networks(client, project, filter):
    # https://cloud.google.com/compute/docs/reference/rest/v1/networks/list
    request = client.networks().list(project = project, filter = filter) # tags such as `tags.items=kubernetes-io-cluster-shoot--core--chaos-gcp-3z` do not work, see https://issuetracker.google.com/issues/120255780#comment14
    networks = []
    while request:
        response = request.execute()
        if 'items' in response:
            for item in response['items']:
                networks.append(Box(item))
        request = client.networks().list_next(previous_request = request, previous_response = response)
    return networks

def list_firewalls(client, project, filter):
    # https://cloud.google.com/compute/docs/reference/rest/v1/firewalls/list
    request = client.firewalls().list(project = project, filter = filter) # tags such as `tags.items=kubernetes-io-cluster-shoot--core--chaos-gcp-3z` do not work, see https://issuetracker.google.com/issues/120255780#comment14
    firewalls = []
    while request:
        response = request.execute()
        if 'items' in response:
            for item in response['items']:
                firewalls.append(Box(item))
        request = client.firewalls().list_next(previous_request = request, previous_response = response)
    return firewalls

def terminate_instance(client, project, zone, instance):
    # https://cloud.google.com/compute/docs/reference/rest/v1/instances/delete
    logger.info(f'Terminating instance {instance} in zone {zone}')
    request = client.instances().delete(project = project, zone = zone, instance = instance, requestId = uuid4())
    response = request.execute()
    return response['name']

def restart_instance(client, project, zone, instance):
    # https://cloud.google.com/compute/docs/reference/rest/v1/instances/reset
    logger.info(f'Restarting instance {instance} in zone {zone}')
    request = client.instances().reset(project = project, zone = zone, instance = instance, requestId = uuid4())
    response = request.execute()
    return response['name']

def tag_instance(client, project, zone, instance, tags, fingerprint):
    # https://cloud.google.com/compute/docs/reference/rest/v1/instances/setTags
    logger.info(f'Tagging instance {instance} in zone {zone} with tags ' + ', '.join(tags))
    request = client.instances().setTags(project = project, zone = zone, instance = instance, body = {'items': tags, 'fingerprint': fingerprint}, requestId = uuid4())
    response = request.execute()
    return response['name']

def suspend_instance(client, project, zone, instance):
    # https://cloud.google.com/compute/docs/reference/rest/v1/instances/suspend
    logger.info(f'Suspending instance {instance} in zone {zone}')
    request = client.instances().suspend(project = project, zone = zone, instance = instance, requestId = uuid4())
    response = request.execute()
    return response['name']

def resume_instance(client, project, zone, instance):
    # https://cloud.google.com/compute/docs/reference/rest/v1/instances/resume
    logger.info(f'Resuming instance {instance} in zone {zone}')
    request = client.instances().resume(project = project, zone = zone, instance = instance, requestId = uuid4())
    response = request.execute()
    return response['name']

def create_firewall(client, project, firewall_name, firewall_body):
    # https://cloud.google.com/compute/docs/reference/rest/v1/firewalls/insert
    logger.info(f'Creating firewall {firewall_name}')
    request = client.firewalls().insert(project = project, body = firewall_body, requestId = uuid4())
    response = request.execute()
    return response['name']

def delete_firewall(client, project, firewall_name):
    # https://cloud.google.com/compute/docs/reference/rest/v1/firewalls/delete
    logger.info(f'Deleting firewall {firewall_name}')
    request = client.firewalls().delete(project = project, firewall = firewall_name, requestId = uuid4())
    response = request.execute()
    return response['name']

def wait_on_zonal_operations(client, project, zone, operations):
    # https://cloud.google.com/compute/docs/reference/rest/v1/zoneOperations/get
    logger.debug(f'Waiting on {len(operations)} zonal operations.')
    for operation in operations:
        wait_on_operation(client.zoneOperations(), project = project, zone = zone, operation = operation)

def wait_on_regional_operations(client, project, region, operations):
    # https://cloud.google.com/compute/docs/reference/rest/v1/regionOperations/get
    logger.debug(f'Waiting on {len(operations)} regional operations.')
    for operation in operations:
        wait_on_operation(client.regionOperations(), project = project, region = region, operation = operation)

def wait_on_global_operations(client, project, operations):
    # https://cloud.google.com/compute/docs/reference/rest/v1/globalOperations/get
    logger.debug(f'Waiting on {len(operations)} global operations.')
    for operation in operations:
        wait_on_operation(client.globalOperations(), project = project, operation = operation)

def wait_on_operation(operations, **kwargs):
    # https://cloud.google.com/compute/docs/api/how-tos/api-requests-responses#handling_api_responses
    logger.debug(f'Waiting on operation {kwargs["operation"]}.')
    try:
        while True:
            operation_result = operations.get(**kwargs).execute()
            if operation_result['status'].lower() == 'done':
                logger.debug(f'Operation returned with result: {operation_result}')
                return operation_result
            else:
                time.sleep(1)
    except Exception as e:
        logger.error(f'Operation failed: {type(e)}: {e}')
