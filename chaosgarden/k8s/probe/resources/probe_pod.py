import base64
import socket
import time
from datetime import datetime, timezone
from subprocess import PIPE, Popen
from threading import Thread
from urllib.parse import urlparse

from flask import Flask, jsonify, request
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

DNS_MGMT_PROBE_MAX_LAG = 60

pod_name = open('/pod/name', 'rt').read()
pod_namespace = open('/pod/namespace', 'rt').read()
zone_name = 'na'
interval = 1
flask_app = Flask(__name__)
k8s_client = None
crd_client = None

#########
# Flask #
#########

@flask_app.route('/livez', methods=['GET'])
def livez():
    return 'OK'

@flask_app.route('/readyz', methods=['GET'])
def readyz():
    return 'OK'

##########
# Probes #
##########

@flask_app.route('/webhook', methods=['POST'])
def webhook_probe():
    req = request.get_json()
    res = {
        'apiVersion': 'admission.k8s.io/v1',
        'kind': 'AdmissionReview',
        'response': {
            'allowed': True,
            'uid': req['request']['uid'],
            'status': {
                'message': f'Probe heart beat acknowledged by {pod_name}'
                }
            }
        }
    jsonpatch = f'[{{"op": "replace", "path": "/ready", "value": true}}, {{"op": "add", "path": "/payload", "value": "{pod_name}"}}]' # https://json8.github.io/patch/demos/apply
    res['response']['patchType'] = 'JSONPatch'
    res['response']['patch']     = base64.b64encode(jsonpatch.encode('utf-8')).decode('utf-8')
    return jsonify(res)

def web_hook_challenger():
    # run challenger
    while True:
        try:
            hb = {
                'apiVersion': 'chaos.gardener.cloud/v1',
                'kind': 'AcknowledgedHeartbeat',
                'metadata': {'name': f'web-hook-probe-regional-{int(datetime.now(tz=timezone.utc).timestamp())}'},
                'ready': False
                }
            crd_client.create_cluster_custom_object(body = hb, group = 'chaos.gardener.cloud', version = 'v1', plural = 'acknowledgedheartbeats', _request_timeout=10) # 5s + mutating web hook timeout seconds
        except ApiException as e:
            if e.status == 409:
                pass # ignore conflict (resource already exists), which may happen if this probe runs with multiple replicas
            else:
                print(f'Web hook challenge resource creation failed: {type(e)}: {e}')
        else:
            print(f'Web hook challenge resource creation succeeded')
        finally:
            time.sleep(interval)

def resolve_ip_from_this_process(host):
    if ':' in host:
        host = urlparse(host).hostname
    _, _, ips = socket.gethostbyname_ex(host) # pylint: disable=E1101
    return host, sorted(ips)[0]

def resolve_ip_from_forked_process(host):
    if ':' in host:
        host = urlparse(host).hostname
    process = Popen([r'python', r'-c', f'import socket; print(sorted(socket.gethostbyname_ex("{host}")[2])[0], end = "")'], stdout=PIPE)
    out, err = process.communicate()
    code = process.wait()
    if err or code:
        raise RuntimeError(f'Resolving {host} returned {code}: {err.decode("utf-8") if err else "n/a"}')
    return host, out.decode('utf-8')

def dns_probe():
    # resolve external and internal fqdn (as baseline)
    ext_fqdn = k8s_client.configuration.host
    int_fqdn = 'kubernetes.default.svc.cluster.local'
    _, ext_ip = resolve_ip_from_this_process(ext_fqdn)
    _, int_ip = resolve_ip_from_this_process(int_fqdn)

    # run probe
    while True:
        try:
            try:
                _, ip = resolve_ip_from_forked_process(ext_fqdn)
                assert ext_ip == ip, f'FQDN {ext_fqdn} should have resolved to {ext_ip}, but resolved to {ip} instead!'
            except Exception as e:
                enqueue('dns-external', False)
                print(f'DNS external probe failed: {type(e)}: {e}')
            else:
                enqueue('dns-external', True)
                print(f'DNS external probe resolved {ext_fqdn} to {ip}')
            try:
                _, ip = resolve_ip_from_forked_process(int_fqdn)
                assert int_ip == ip, f'FQDN {int_fqdn} should have resolved to {int_ip}, but resolved to {ip} instead!'
            except Exception as e:
                enqueue('dns-internal', False)
                print(f'DNS internal probe failed: {type(e)}: {e}')
            else:
                enqueue('dns-internal', True)
                print(f'DNS internal probe resolved {int_fqdn} to {ip}')
        except Exception as e:
            print(f'DNS probe failed: {type(e)}: {e}')
        finally:
            time.sleep(interval)

def create_dns_mgmt_test_record(fqdn):
    # define dns management test record
    now = datetime.now(tz=timezone.utc)
    return {
        'apiVersion': 'dns.gardener.cloud/v1alpha1',
        'kind': 'DNSEntry',
        'metadata': {
            'annotations': {'dns.gardener.cloud/class': 'garden'},
            'name': fqdn.split('.')[0],
            'namespace': 'chaos-garden-probe'},
        'spec': {
            'dnsName': fqdn,
            'ttl': 1,
            'targets': [f'10.{now.hour}.{now.minute}.{now.second}']}
        }

def dns_mgmt_updater(fqdn):
    # create dns management test record
    try:
        crd_client.create_namespaced_custom_object(body = create_dns_mgmt_test_record(fqdn), namespace = 'chaos-garden-probe', group = 'dns.gardener.cloud', version = 'v1alpha1', plural = 'dnsentries', _request_timeout=5)
    except ApiException as e:
        if e.status == 409:
            pass # ignore conflict (resource already exists), which may happen if the test record wasn't properly removed
        else:
            print(f'DNS management test record initialization failed: {type(e)}: {e}')
    except Exception as e:
        print(f'DNS management test record initialization failed: {type(e)}: {e}')

    # run updater
    while True:
        try:
            crd_client.patch_namespaced_custom_object(body = create_dns_mgmt_test_record(fqdn), name = fqdn.split('.')[0], namespace = 'chaos-garden-probe', group = 'dns.gardener.cloud', version = 'v1alpha1', plural = 'dnsentries', _request_timeout=5)
        except Exception as e:
            print(f'DNS management test record update failed: {type(e)}: {e}')
        else:
            print(f'DNS management test record update succeeded')
        finally:
            time.sleep(interval)

def dns_mgmt_probe():
    # compute dns management test record fqdn
    fqdn = f'chaosgarden-dns-mgmt-probe-test-record-{zone_name}.' + client.CoreV1Api(k8s_client).read_namespaced_config_map('shoot-info', 'kube-system').data['domain']

    # launch dns management test record updater
    thread = Thread(name = 'dns_mgmt_updater', target = dns_mgmt_updater, args = [fqdn])
    thread.setDaemon(True)
    thread.start()

    # run probe
    resolve_succeeded_once = False
    while True:
        try:
            _, ip = resolve_ip_from_forked_process(fqdn)
            resolve_succeeded_once = True
            ip = [int(segment) for segment in ip.split('.')]
            now = datetime.now(tz=timezone.utc)
            now_timestamp = (((now.hour * 60) + now.minute) * 60) + now.second
            ip_timestamp = (((ip[1] * 60) + ip[2]) * 60) + ip[3]
            lag = (now_timestamp - ip_timestamp) if now_timestamp >= ip_timestamp else (24*60*60 + now_timestamp - ip_timestamp)
        except Exception as e:
            if resolve_succeeded_once:
                enqueue('dns-management', False)
            print(f'DNS management probe failed: {type(e)}: {e}')
        else:
            enqueue('dns-management', lag <= DNS_MGMT_PROBE_MAX_LAG, str(lag))
            print(f'DNS management probe succeeded with a lag of {lag}s')
        finally:
            time.sleep(interval)

def api_probe():
    # put together internal Kubernetes client configuration
    int_k8s_cfg = client.Configuration()
    int_k8s_cfg.host = 'https://kubernetes.default.svc.cluster.local'
    int_k8s_cfg.api_key_prefix['authorization'] = 'Bearer'
    int_k8s_cfg.api_key['authorization'] = open('/var/run/secrets/kubernetes.io/serviceaccount/token', 'rt').read()
    int_k8s_cfg.ssl_ca_cert = '/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'
    int_k8s_client = client.ApiClient(int_k8s_cfg)

    # run probe
    while True:
        try:
            try:
                ext_version_client = client.VersionApi(k8s_client)
                version = ext_version_client.get_code()
            except Exception as e:
                enqueue('api-external', False)
                print(f'API external probe failed: {type(e)}: {e}')
            else:
                enqueue('api-external', True)
                print(f'API external probe read v{version.major}.{version.minor} using {ext_version_client.api_client.configuration.host}')
            try:
                int_version_client = client.VersionApi(int_k8s_client)
                version = int_version_client.get_code()
            except Exception as e:
                enqueue('api-internal', False)
                print(f'API internal probe failed: {type(e)}: {e}')
            else:
                enqueue('api-internal', True)
                print(f'API internal probe read v{version.major}.{version.minor} using {int_version_client.api_client.configuration.host}')
        except Exception as e:
            print(f'API probe failed: {type(e)}: {e}')
        finally:
            time.sleep(interval)

###########
# Emitter #
###########

def enqueue(probe, ready, payload = None):
    # create and enqueue new heart beat
    print(f'Creating heart beat for probe {probe} with ready={ready} and payload={payload}...')
    hb = {
        'apiVersion': 'chaos.gardener.cloud/v1',
        'kind': 'Heartbeat',
        'metadata': {'name': f'{probe}-probe-{zone_name}-{int(datetime.now(tz=timezone.utc).timestamp())}'},
        'ready': ready
        }
    if payload != None:
        hb['payload'] = payload
    print(f'Enqueuing heart beat: {hb}')
    thread = Thread(name = 'heart_beat_emitter', target = emit, args = [hb])
    thread.setDaemon(True)
    thread.start()

def emit(hb):
    # emit
    while True:
        try:
            print(f'Sending heart beat: {hb}')
            crd_client.create_cluster_custom_object(body = hb, group = 'chaos.gardener.cloud', version = 'v1', plural = 'heartbeats', _request_timeout=5)
        except Exception as e:
            print(f'Heart beat emitter failed: {type(e)}: {e}')
            time.sleep(1) # back-off
        else:
            print(f'Heart beat emitter succeeded')
            return


########
# Main #
########

if __name__ == '__main__':
    # create Kubernetes clients
    config.load_incluster_config()
    k8s_client = client.ApiClient()
    crd_client = client.CustomObjectsApi(k8s_client)

    # retrieve pod and node to resolve placement zone
    core_client = client.CoreV1Api(k8s_client)
    pod = core_client.read_namespaced_pod(pod_name, pod_namespace)
    node = core_client.read_node(pod.spec.node_name)
    zone_name = node.metadata.labels['topology.kubernetes.io/zone']

    # start heart beat emitter
    thread = Thread(name = 'heart_beat_emitter', target = emit)
    thread.setDaemon(True)
    thread.start()

    # start threads
    for target in [web_hook_challenger, dns_probe, dns_mgmt_probe, api_probe]:
        thread = Thread(name = target.__name__, target = target)
        thread.setDaemon(True)
        thread.start()

    # run flask (blocking)
    while True:
        try:
            flask_app.run(host='0.0.0.0', port=8080, ssl_context=('/tls/webhook.crt', '/tls/webhook.key'))
        except Exception as e:
            print(f'Flask failed: {type(e)}: {e}')
            time.sleep(1) # back-off
