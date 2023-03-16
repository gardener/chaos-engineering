import base64
import json

from chaosgarden.k8s.api.cluster import API, Cluster

ADMIN_KUBECONFIG_REQUEST = {
    'apiVersion': 'authentication.gardener.cloud/v1alpha1',
    'kind': 'AdminKubeconfigRequest',
    'spec': {
        'expirationSeconds': 86400}}


def get_kubeconfig(garden_cluster: Cluster, project_namespace: str, shoot_name: str) -> str:
    return base64.b64decode(garden_cluster.client(API.Plain).post(
        f'/apis/core.gardener.cloud/v1beta1/namespaces/{project_namespace}/shoots/{shoot_name}/adminkubeconfig',
        json.dumps(ADMIN_KUBECONFIG_REQUEST))['status']['kubeconfig']).decode('utf-8')
