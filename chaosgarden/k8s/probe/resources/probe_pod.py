import base64
import re
import signal
import socket
import time
from datetime import datetime, timezone
from queue import Queue
from subprocess import PIPE, Popen
from threading import Lock, Thread, current_thread
from urllib.parse import urlparse

from flask import Flask, jsonify, request
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

DNS_MGMT_PROBE_MAX_LAG = 60

pod_name = open('/pod/name', 'rt').read()
pod_namespace = open('/pod/namespace', 'rt').read()
zone_name = 'na'
interval = 1
queue = Queue()
lock = Lock()
in_termination = False
flask_app = Flask(__name__)
main_thread = current_thread()


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
                'message': f'Probe heartbeat acknowledged by {pod_name}'
                }
            }
        }
    jsonpatch = f'[{{"op": "replace", "path": "/ready", "value": true}}, {{"op": "add", "path": "/payload", "value": "acknowledged by {pod_name} in {zone_name}"}}]' # https://json8.github.io/patch/demos/apply
    res['response']['patchType'] = 'JSONPatch'
    res['response']['patch']     = base64.b64encode(jsonpatch.encode('utf-8')).decode('utf-8')
    return jsonify(res)

def web_hook_challenger():
    # initialise client
    crd_client = None

    # run challenger
    while not is_terminated():
        try:
            hb = {
                'apiVersion': 'chaos.gardener.cloud/v1',
                'kind': 'AcknowledgedHeartbeat',
                'metadata': {'name': f'web-hook-probe-regional-{int(datetime.now(tz=timezone.utc).timestamp())}'},
                'ready': False
                }
            if not crd_client:
                crd_client = client.CustomObjectsApi(client.ApiClient())
            crd_client.create_cluster_custom_object(body = hb, group = 'chaos.gardener.cloud', version = 'v1', plural = 'acknowledgedheartbeats', _request_timeout = 15) # mutating web hook timeout seconds
        except Exception as e:
            if isinstance(e, ApiException) and e.status == 409:
                pass # ignore conflict (resource already exists), which may happen if this probe runs with multiple replicas
            else:
                print(f'Web hook challenge resource creation failed: {type(e)}: {e}')
                crd_client = None
        else:
            print(f'Web hook challenge resource creation succeeded')
        finally:
            time.sleep(interval)

def resolve_all_ips_from_this_process(host):
    if ':' in host:
        host = urlparse(host).hostname
    _, _, ips = socket.gethostbyname_ex(host) # pylint: disable=E1101
    return host, sorted(ips)

def resolve_any_ip_from_forked_process(host):
    if ':' in host:
        host = urlparse(host).hostname
    process = Popen([r'python', r'-c', f'import socket; print(socket.gethostbyname_ex("{host}")[2][0], end = "")'], stdout=PIPE)
    out, err = process.communicate()
    code = process.wait()
    if err or code:
        raise RuntimeError(f'Resolving FQDN {host} returned exit code {code}: {err.decode("utf-8") if err else "n/a"}')
    return host, out.decode('utf-8')

def dns_probe():
    # resolve external and internal fqdn (as baseline)
    ext_fqdn = client.ApiClient().configuration.host
    int_fqdn = 'kubernetes.default.svc.cluster.local'
    _, ext_ips = resolve_all_ips_from_this_process(ext_fqdn)
    _, int_ips = resolve_all_ips_from_this_process(int_fqdn)
    print(f'DNS external probe resolved FQDN {ext_fqdn} to {ext_ips}')
    print(f'DNS internal probe resolved FQDN {int_fqdn} to {int_ips}')

    # run probe
    while not is_terminated():
        try:
            try:
                _, ip = resolve_any_ip_from_forked_process(ext_fqdn)
                assert re.match(r'^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$', ip), f'FQDN {ext_fqdn} resolved to something that does not look like an IP ({ip}) but should be one of {ext_ips}!'
            except Exception as e:
                enqueue('dns-external', False, e)
                print(f'DNS external probe failed: {type(e)}: {e}')
            else:
                enqueue('dns-external', True, ip)
                print(f'DNS external probe resolved {ext_fqdn} to {ip}')
            try:
                _, ip = resolve_any_ip_from_forked_process(int_fqdn)
                assert re.match(r'^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$', ip), f'FQDN {int_fqdn} resolved to something that does not look like an IP ({ip}) but should be one of {int_ips}!'
            except Exception as e:
                enqueue('dns-internal', False, e)
                print(f'DNS internal probe failed: {type(e)}: {e}')
            else:
                enqueue('dns-internal', True, ip)
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
    # initialise client
    crd_client = None

    # run updater
    record_created = False
    while not is_terminated():
        operation = 'operation'
        try:
            if not crd_client:
                crd_client = client.CustomObjectsApi(client.ApiClient())
            if not record_created:
                operation = 'initialization'
                crd_client.create_namespaced_custom_object(body = create_dns_mgmt_test_record(fqdn), namespace = 'chaos-garden-probe', group = 'dns.gardener.cloud', version = 'v1alpha1', plural = 'dnsentries', _request_timeout = 5)
                record_created = True
            else:
                operation = 'update'
                crd_client.patch_namespaced_custom_object(body = create_dns_mgmt_test_record(fqdn), name = fqdn.split('.')[0], namespace = 'chaos-garden-probe', group = 'dns.gardener.cloud', version = 'v1alpha1', plural = 'dnsentries', _request_timeout = 5)
        except Exception as e:
            if isinstance(e, ApiException) and e.status == 409 and not record_created:
                record_created = True # ignore conflict (resource already exists), which may happen if the test record wasn't properly removed
            else:
                print(f'DNS management test record {operation} failed: {type(e)}: {e}')
                crd_client = None
        else:
            print(f'DNS management test record {operation} succeeded')
        finally:
            time.sleep(interval)

def dns_mgmt_probe():
    # compute dns management test record fqdn
    fqdn = f'chaosgarden-dns-mgmt-probe-test-record-{zone_name}.' + client.CoreV1Api(client.ApiClient()).read_namespaced_config_map('shoot-info', 'kube-system').data['domain']

    # launch dns management test record updater
    thread = Thread(name = 'dns_mgmt_updater', target = dns_mgmt_updater, args = [fqdn])
    thread.setDaemon(True)
    thread.start()

    # run probe
    resolve_succeeded_once = False
    while not is_terminated():
        try:
            _, ip = resolve_any_ip_from_forked_process(fqdn)
            resolve_succeeded_once = True
            ip = [int(segment) for segment in ip.split('.')]
            now = datetime.now(tz=timezone.utc)
            now_timestamp = (((now.hour * 60) + now.minute) * 60) + now.second
            ip_timestamp = (((ip[1] * 60) + ip[2]) * 60) + ip[3]
            lag = (now_timestamp - ip_timestamp) if now_timestamp >= ip_timestamp else (24*60*60 + now_timestamp - ip_timestamp)
        except Exception as e:
            if resolve_succeeded_once:
                enqueue('dns-management', False, e)
            print(f'DNS management probe failed: {type(e)}: {e}')
        else:
            enqueue('dns-management', lag <= DNS_MGMT_PROBE_MAX_LAG, f'lags {lag}s')
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

    # initialise clients
    ext_version_client = None
    int_version_client = None

    # run probe
    while not is_terminated():
        try:
            try:
                if not ext_version_client:
                    ext_version_client = client.VersionApi(client.ApiClient())
                version = ext_version_client.get_code(_request_timeout = 5)
            except Exception as e:
                enqueue('api-external', False, e)
                print(f'API external probe failed: {type(e)}: {e}')
                ext_version_client = None
            else:
                enqueue('api-external', True)
                print(f'API external probe read v{version.major}.{version.minor} using {ext_version_client.api_client.configuration.host}')
            try:
                if not int_version_client:
                    int_version_client = client.VersionApi(client.ApiClient(int_k8s_cfg))
                version = int_version_client.get_code(_request_timeout = 5)
            except Exception as e:
                enqueue('api-internal', False, e)
                print(f'API internal probe failed: {type(e)}: {e}')
                int_version_client = None
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
    # create and enqueue heartbeat
    print(f'Creating heartbeat for probe {probe} with ready={ready} and payload={payload}...')
    hb = {
        'apiVersion': 'chaos.gardener.cloud/v1',
        'kind': 'Heartbeat',
        'metadata': {'name': f'{probe}-probe-{zone_name}-{int(datetime.now(tz=timezone.utc).timestamp())}'},
        'ready': ready
        }
    if payload != None:
        hb['payload'] = str(payload).replace('\n', '⏎')
    print(f'Enqueuing heartbeat: {hb}')
    queue.put(hb)

def emit():
    # initialise client
    crd_client = None

    # emit heartbeat
    while not is_terminated() or queue.qsize() > 0:
        print(f'Emitter queue holds {queue.qsize()} heartbeats')
        try:
            hb = queue.get(block = True, timeout = 1) # re-check for termination
            try:
                print(f'Sending heartbeat: {hb}')
                if not crd_client:
                    crd_client = client.CustomObjectsApi(client.ApiClient())
                crd_client.create_cluster_custom_object(body = hb, group = 'chaos.gardener.cloud', version = 'v1', plural = 'heartbeats', _request_timeout = 5)
            except Exception as e:
                if isinstance(e, ApiException) and e.status == 409:
                    print(f'Sending heartbeat failed (conflict): {hb} -> ApiException: 409')
                else:
                    print(f'Sending heartbeat failed (other): {hb} -> {type(e)}: {e}')
                    crd_client = None
                    queue.put(hb) # retry
                    time.sleep(1) # back-off
            else:
                print(f'Sending heartbeat succeeded: {hb}')
        except:
            pass


########
# Main #
########

def signal_handler_called(signal_number = None, stack_frame = None): # signature implements signal.signal() handler interface
    print(f'Signal handler invoked ({signal.Signals(signal_number).name}). Aborting now.')
    with lock:
        global in_termination
        in_termination = True
        raise RuntimeError(f'{signal.Signals(signal_number).name} received. Abort now.')

def is_terminated():
    with lock:
        return in_termination

if __name__ == '__main__':
    # install signal handlers
    signal.signal(signal.SIGTERM, signal_handler_called)
    signal.signal(signal.SIGQUIT, signal_handler_called)
    signal.signal(signal.SIGINT, signal_handler_called)

    # load in-cluster config for all in-cluster clients to be (re-)created from later
    # (we will recreate a client when a probe failed, so that we can react to changes in API server DNS/routing)
    config.load_incluster_config()

    # retrieve pod and node to resolve placement zone
    core_client = client.CoreV1Api(client.ApiClient())
    pod = core_client.read_namespaced_pod(pod_name, pod_namespace)
    node = core_client.read_node(pod.spec.node_name)
    zone_name = node.metadata.labels['topology.kubernetes.io/zone']

    # start heartbeat emitter
    emitter_thread = Thread(name = 'heart_beat_emitter', target = emit)
    emitter_thread.setDaemon(True)
    emitter_thread.start()
    print(f'Thread {emitter_thread.name} started.')

    # start threads
    threads = []
    for target in [web_hook_challenger, dns_probe, dns_mgmt_probe, api_probe]:
        thread = Thread(name = target.__name__, target = target)
        threads.append(thread)
        thread.setDaemon(True)
        thread.start()
        print(f'Thread {thread.name} started.')

    # run flask (blocking)
    while not is_terminated():
        try:
            flask_app.run(host='0.0.0.0', port=8080, ssl_context=('/tls/webhook.crt', '/tls/webhook.key'))
        except Exception as e:
            print(f'Flask stopped: {type(e)}: {e}')
            time.sleep(1) # back-off

    # join threads
    for thread in threads:
        thread.join()
        print(f'Thread {thread.name} joined. Waiting for more.')
    emitter_thread.join()
    print(f'Thread {emitter_thread.name} joined. Terminating now.')
