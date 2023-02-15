# **Module: `garden`**

## Purpose

### What?

This module provides [`chaostoolkit`](https://chaostoolkit.org) actions to simulate zone outages and disrupt pods in Gardener-managed clusters. It supports:

- **Compute**: *Termination* or *hard restart/reboot* of nodes in one zone with a min/max lifetime (e.g. 0s-0s to shoot down any machine right when it tries to come up or e.g. 10-60s to let them come up at least for 10s but shoot them down at the latest after 60s).
- **Network**: Blocking only *ingress* or only *egress* or *all* network traffic for nodes in one zone.
- **Pods**: *Termination* of control plane pods (depends on your access permissions - end users have no access), system component pods (Gardener-managed addons in your `kube-system` namespace), or pods in general in one zone with a min/max lifetime (e.g. 0s-0s to shoot down any pod right when it tries to come up or e.g. 10-60s to let them come up at least for 10s but shoot them down at the latest after 60s) with or without a grace period.

You can run the above in parallel, even of the same type, as long as the targeted zones differ. This way you can also test whether you recover after a multi-zonal outage.

This module also provides [`chaostoolkit`](https://chaostoolkit.org) probes:

- **Health Probe**: Probes various Gardener-managed cluster functions in parallel.

:warning: The probe requires resources that have not yet been shared as of today (dynamic cert generation must be implemented first), so it isn't usable today for you, unless you have also access to said resources.

### How?

- **Compute** and **Network**: See [cloud provider specific docs](/readme.md#cloud-providers).
- **Pods**: Based on the given zone and filters, pods are identified busily/continuously and *terminated* with or without a grace period. You may provide a min/max lifetime to make the process more random, chaotic, and unpredictable, which may further help you unearth issues.
- **Health Probe**: Deploys probes into the cluster that busily/continuously probe various Gardener-managed cluster functions in parallel. This operation must be rolled back when completed.

### Why?

Implementing high availability that can even tolerate a zone outage unscathed is no trivial task. You can find more information on how to achieve this goal [here](/docs/garden/high-availability.md). To put your solution to the test, this module will help you.

The probe on the other hand is targeting Gardener developers and output-qualification and puts Gardener HA as such to the test, which requires automation as Gardener-managed clusters perform many functions in parallel.

## Usage

### Actions and Rollbacks

`chaostoolkit` introduces so-called [actions](https://chaostoolkit.org/reference/api/experiment/#action) that can be composed into [experiments](https://chaostoolkit.org/reference/api/experiment/#experiment) that perform operations against a system (here a Gardener-managed Kubernetes cluster). The following actions (and explicit [rollbacks](https://chaostoolkit.org/reference/api/experiment/#rollbacks)) are supported:

Module: [`chaosgarden.garden.actions`](/chaosgarden/garden/actions.py)

- `assess_cloud_provider_filters_impact`: Show which machines/networks would be affected by the given zone and filters. Useful in combination with [wait-for](/docs/human/readme.md) before launching the actual action.
- `run_cloud_provider_compute_failure_simulation`: Run compute failure simulation.
- `run_cloud_provider_compute_failure_simulation_in_background`: Same as above, but running in background as a thread. Normally not used with experiments, but directly in Python (scripts).
- `run_cloud_provider_network_failure_simulation`: Run network failure simulation.
- `rollback_cloud_provider_network_failure_simulation`: Rollback network failure simulation explicitly (usually performed automatically above, but can also be invoked explicitly as rollback step in an experiment to deal with interruptions).
- `run_cloud_provider_network_failure_simulation_in_background`: Same as above, but running in background as a thread. Normally not used with experiments, but directly in Python (scripts).

- `run_control_plane_pod_failure_simulation`: Run control plane pod failure simulation (depends on your access permissions - end users have no access).
- `run_control_plane_pod_failure_simulation_in_background`: Same as above, but running in background as a thread. Normally not used with experiments, but directly in Python (scripts).
- `run_system_components_pod_failure_simulation`: Run system component pod failure simulation (Gardener-managed addons in your `kube-system` namespace).
- `run_system_components_pod_failure_simulation_in_background`: Same as above, but running in background as a thread. Normally not used with experiments, but directly in Python (scripts).
- `run_general_pod_failure_simulation`: Run general pod failure simulation.
- `run_general_pod_failure_simulation_in_background`: Same as above, but running in background as a thread. Normally not used with experiments, but directly in Python (scripts).

- `run_shoot_cluster_health_probe`: Run shoot cluster health probe (usually only interesting to Gardener developers).
- `rollback_shoot_cluster_health_probe`: Rollback shoot cluster health probe explicitly (usually performed automatically above, but can also be invoked explicitly as rollback step in an experiment to deal with interruptions).
- `run_shoot_cluster_health_probe_in_background`: Same as above, but running in background as a thread. Normally not used with experiments, but directly in Python (scripts).

### Pod Selectors

The following pod selectors are supported:

- `node_label_selector`, e.g. `topology.kubernetes.io/zone=world-1a,worker.gardener.cloud/pool=cpu-worker,...`, right-hand side may be a regex, operators are `=|==|!=|=~|!~`
- `pod_label_selector`, e.g. `gardener.cloud/role=controlplane,gardener.cloud/role=vpa,...`, regular [pod label selector](https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/#label-selectors) (not interpreted by `chaosgarden`)
- `pod_metadata_selector`, e.g. `namespace=kube-system,name=kube-apiserver.*,...`, right-hand side may be a regex, operators are `=|==|!=|=~|!~`
- `pod_owner_selector`, e.g. `kind!=DaemonSet,name=kube-apiserver.*,...`, right-hand side may be a regex, operators are `=|==|!=|=~|!~`

### Configuration

The following [configuration](https://chaostoolkit.org/reference/api/experiment/#configuration) fields are mandatory:

- `project`: Gardener project name
- `shoot`: Shoot cluster name

### Secrets

The following [secret](https://chaostoolkit.org/reference/api/experiment/#secrets) fields are optional (only one is permitted; if none is set, `$KUBECONFIG` is assumed to be pointing to Gardener):

- `kubeconfig_struct`: Kubernetes cluster configuration for Gardener (json struct)
- `kubeconfig_file`: Kubernetes cluster configuration for Gardener (path to kubeconfig file)
- `kubeconfig_envvar`: Kubernetes cluster configuration for Gardener (env var with path to kubeconfig file)

## Examples

- [Assess Filters Impact](/docs/garden/assess-filters-impact.json)
- [Run Compute Failure Simulation](/docs/garden/run-compute-failure-simulation.json)
- [Run Network Failure Simulation](/docs/garden/run-network-failure-simulation.json)

- [Run Control Plane Pod Failure Simulation](/docs/garden/run-control-plane-pod-failure-simulation.json)
- [Run System Components Pod Failure Simulation](/docs/garden/run-system-components-pod-failure-simulation.json)
- [Run General Pod Failure Simulation](/docs/garden/run-general-pod-failure-simulation.json)

- [Run Shoot Cluster Health Probe as Hypothesis](/docs/garden/run-shoot-cluster-health-probe-as-hypothesis.json) (doesn't really fit as it must run in background, which is not supported by `chaostoolkit`)
- [Run Shoot Cluster Health Probe as Method](/docs/garden/run-shoot-cluster-health-probe-as-method.json) (the better alternative and almost identical in `chaostoolkit` behavior)

- [Explicit Garden Secrets](/docs/garden/explicit-garden-secrets.json) (if you do not want to use `$KUBECONFIG` pointing to Gardener)
