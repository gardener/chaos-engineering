import openstack
from logzero import logger


def openstack_connection(configuration, secrets):
    # https://docs.openstack.org/openstacksdk/latest/user/index.html#api-documentation
    # https://docs.openstack.org/openstacksdk/latest/user/connection.html#using-only-keyword-arguments
    # https://opendev.org/openstack/openstacksdk/src/branch/master/openstack/connection.py
    # https://opendev.org/openstack/openstacksdk/src/branch/master/openstack/config/loader.py
    # https://stackoverflow.com/questions/73649308/openstack-python-api-how-create-a-connection-using-application-credentials
    # https://docs.openstack.org/openstacksdk/latest/user/proxies/compute.html
    # https://opendev.org/openstack/openstacksdk/src/branch/master/openstack/compute/v2
    return openstack.connect(
        region_name         = configuration['openstack_region'],
        compute_api_version = '2',
        **secrets)

def list_servers(conn, zone, status, filter):
    # https://docs.openstack.org/openstacksdk/latest/user/guides/compute.html#list-servers
    # https://opendev.org/openstack/openstacksdk/src/branch/master/openstack/compute/v2/_proxy.py#L792
    # https://docs.openstack.org/api-ref/compute/?expanded=list-servers-detail#list-servers (allowed states and allowed filters)
    # filtering by `availability_zone` is supported only from `v2.83`, which is not available widely enough yet, and
    # filtering by metadata is not supported at all (as of now, Gardener sets metadata instead of tags)
    filter = dict(filter)
    if isinstance(status, str):
        filter['status'] = status
    metadata = filter.pop('metadata', None)
    servers = []
    for server in conn.compute.servers(**filter):
        if (server.availability_zone == zone) and (not metadata or metadata in server.metadata) and (not isinstance(status, list) or server.status in status):
            # https://opendev.org/openstack/openstacksdk/src/branch/master/openstack/compute/v2/server.py
            servers.append(server)
    return servers

def terminate_server(conn, server):
    # https://docs.openstack.org/openstacksdk/latest/user/proxies/compute.html#server-operations
    logger.info(f'Terminating server {server.name} in zone {server.availability_zone}')
    conn.compute.delete_server(server, force = True)
    # https://opendev.org/openstack/openstacksdk/src/branch/master/openstack/compute/v2/_proxy.py#L2396
    # conn.compute.wait_for_delete(server)
    # logger.info(f'Terminated server {server.name} in zone {server.availability_zone}')

def restart_server(conn, server):
    # https://docs.openstack.org/openstacksdk/latest/user/proxies/compute.html#starting-stopping-etc
    logger.info(f'Restarting server {server.name} in zone {server.availability_zone}')
    conn.compute.reboot_server(server, reboot_type = 'HARD')
    # https://opendev.org/openstack/openstacksdk/src/branch/master/openstack/compute/v2/_proxy.py#L2365
    # conn.compute.wait_for_server(server, status = 'ACTIVE')
    # logger.info(f'Restarted server {server.name} in zone {server.availability_zone}')

def create_sg(conn, sg_attrs, sgr_attrs_list):
    # https://docs.openstack.org/openstacksdk/latest/user/proxies/network.html#security-group-operations
    logger.info(f'Creating sg {sg_attrs["name"]}')
    # https://opendev.org/openstack/openstacksdk/src/branch/master/openstack/network/v2/_proxy.py#L3708
    sg = conn.network.create_security_group(**sg_attrs)
    for sgr in sg.security_group_rules:
        # delete default security group rules
        # https://opendev.org/openstack/openstacksdk/src/branch/master/openstack/network/v2/_proxy.py#L3836
        conn.network.delete_security_group_rule(sgr)
    for sgr_attrs in sgr_attrs_list:
        # https://opendev.org/openstack/openstacksdk/src/branch/master/openstack/network/v2/_proxy.py#L3807
        conn.network.create_security_group_rule(security_group_id = sg.id, **sgr_attrs)
    return sg

def delete_sg(conn, sg_name):
    # https://docs.openstack.org/openstacksdk/latest/user/proxies/network.html#security-group-operations
    logger.info(f'Deleting sg {sg_name}')
    # https://opendev.org/openstack/openstacksdk/src/branch/master/openstack/network/v2/_proxy.py#L3741
    sg = conn.network.find_security_group(sg_name)
    if sg:
        # https://opendev.org/openstack/openstacksdk/src/branch/master/openstack/network/v2/_proxy.py#L3720
        conn.network.delete_security_group(sg)
    return sg
