import sys
from datetime import datetime, timezone

from kubernetes import client, config

pod_name = open('/pod/name', 'rt').read()
pod_namespace = open('/pod/namespace', 'rt').read()


########
# Main #
########

if __name__ == '__main__':
    # create Kubernetes clients
    config.load_incluster_config()
    k8s_client = client.ApiClient()
    core_client = client.CoreV1Api(k8s_client)
    crd_client = client.CustomObjectsApi(k8s_client)

    # send heart beat
    try:
        # retrieve pod and node to resolve placement zone
        pod = core_client.read_namespaced_pod(pod_name, pod_namespace)
        restart_count = pod.status.container_statuses[0].restart_count
        node = core_client.read_node(pod.spec.node_name)
        zone_name = node.metadata.labels['topology.kubernetes.io/zone']

        # create heart beat resource
        hb_name = f'pod-lifecycle-probe-{zone_name}-{int(datetime.now(tz=timezone.utc).timestamp())}'
        hb_ready = True if restart_count == 0 else False
        print(f'About to send heart beat {hb_name} with readiness {hb_ready}...')
        hb = {
            'apiVersion': 'chaos.gardener.cloud/v1',
            'kind': 'Heartbeat',
            'metadata': {'name': hb_name},
            'ready': hb_ready
            }
        crd_client.create_cluster_custom_object(body = hb, group = 'chaos.gardener.cloud', version = 'v1', plural = 'heartbeats', _request_timeout=5)
        print(f'Heart beat sent successfully')
    except Exception as e:
        print(f'Heart beat not sent: {type(e)}: {e}')
        raise e

    # kill this pod
    try:
        print(f'About to kill pod {pod_namespace}/{pod_name}...')
        core_client.delete_namespaced_pod(pod_name, pod_namespace, grace_period_seconds=0, async_req = True, _request_timeout=5)
        print(f'Pod killed successfully') # everything here and lower may already be cut off
    except Exception as e:
        print(f'Pod not killed: {type(e)}: {e}')
        sys.exit(-1)
    else:
        sys.exit(0)
