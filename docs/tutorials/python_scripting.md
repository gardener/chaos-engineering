<!-- BEGIN of section that must be kept in sync with sibling tutorial -->
## Overview

Gardener provides [`chaostoolkit`](https://chaostoolkit.org) modules to simulate *compute* and *network* outages for various cloud providers such as [AWS](https://github.com/gardener/chaos-engineering/tree/main/docs/aws), [Azure](https://github.com/gardener/chaos-engineering/tree/main/docs/azure), [GCP](https://github.com/gardener/chaos-engineering/tree/main/docs/gcp), [OpenStack/Converged Cloud](https://github.com/gardener/chaos-engineering/tree/main/docs/openstack), and [VMware vSphere](https://github.com/gardener/chaos-engineering/tree/main/docs/vsphere), as well as *pod disruptions* for [any Kubernetes cluster](https://github.com/gardener/chaos-engineering/tree/main/docs/k8s).

The API, parameterization, and implementation is as homogeneous as possible across the different cloud providers, so that you have only minimal effort. As a Gardener user, you benefit from an [additional `garden` module](https://github.com/gardener/chaos-engineering/tree/main/docs/garden) that leverages the generic modules, but exposes their functionality in the most simple, homogeneous, and secure way (no need to specify cloud provider credentials, cluster credentials, or filters explicitly; retrieves credentials and stores them in memory only).

## Installation

The name of the package is `chaosgarden` and it was developed and tested with Python 3.9+. It's being published to [PyPI](https://pypi.org/project/chaosgarden), so that you can comfortably install it via Python's package installer [pip](https://pip.pypa.io/en/stable) (you may want to [create a virtual environment](https://packaging.python.org/en/latest/guides/installing-using-pip-and-virtual-environments/#creating-a-virtual-environment) before installing it):

``` sh
pip install chaosgarden
```

ℹ️ If you want to use the [VMware vSphere module](https://github.com/gardener/chaos-engineering/tree/main/docs/vsphere), please note the remarks in [`requirements.txt`](https://github.com/gardener/chaos-engineering/blob/main/requirements.txt) for `vSphere`. Those are not contained in the published PyPI package.

The package can be used directly from Python scripts and supports this usage scenario with additional convenience that helps launch actions and probes in background (more on actions and probes later), so that you can compose also complex scenarios with ease.
<!-- END of section that must be kept in sync with sibling tutorial -->

<!-- BEGIN of section that must be kept in sync with sibling tutorial -->
## Usage

ℹ️ We assume you are using Gardener and run Gardener-managed shoot clusters. You can also use the generic cloud provider and Kubernetes `chaosgarden` modules, but configuration and secrets will then differ. Please see the [module docs](/docs) for details.
<!-- END of section that must be kept in sync with sibling tutorial -->

### A Simple Script

All actions and probes in `chaosgarden` natively support a background mode (methods ending with `_in_background`), which makes it even easier to compose complex scenarios. To illustrate this, let's take down 2 zones in parallel 🪓, the first for `120s` and the second for `60s`. Ideally, you have a shoot cluster with 3 zones with some workload of yours that would be sensitive to such a scenario and that you monitor, e.g. some quorum-based workload like ETCD that will temporarily lose quorum for the first `60s` when 2 zones are down and then regain quorum afterwards even though the first zone remains down for another `60s`.

Let's assume, your project is called `my-project` and your shoot is called `my-shoot`, then we need to create the following script:

``` python
import os
import sys

from chaosgarden.garden.actions import (
    assess_cloud_provider_filters_impact,
    run_cloud_provider_network_failure_simulation_in_background)

if __name__ == '__main__':
    # compose experiment configuration
    configuration = {
        'garden_project': 'my-project',
        'garden_shoot':   'my-shoot'}

    # assess cloud provider resources and ask for confirmation
    assess_cloud_provider_filters_impact(zone = 0, configuration = configuration)
    assess_cloud_provider_filters_impact(zone = 1, configuration = configuration)
    print('Please confirm running a (double) zone outage against the above resources.')
    reply = input('Press `Y` to continue... ')
    if not reply or reply.lower()[0] != 'y':
        print('No confirmation. Aborting now.')
        sys.exit(0)

    # launch simulations in parallel in background
    zone_0_failure = run_cloud_provider_network_failure_simulation_in_background(
        zone = 0, duration = 120, configuration = configuration)
    zone_1_failure = run_cloud_provider_network_failure_simulation_in_background(
        zone = 1, duration =  60, configuration = configuration)

    # wait for simulations to end and join threads of destruction
    zone_0_failure.join()
    zone_1_failure.join()
```

It assesses first the impacted cloud provider resources and asks for confirmation before it takes down the first zone for `120s` and the second zone for `60s` in parallel. It then waits for both "threads of descruction" 🪓 to end and joins them (the `_in_background` versions of `chaosgarden` actions and probes return [`Thread` objects](https://docs.python.org/3/library/threading.html#thread-objects)).

<!-- BEGIN of section that must be kept in sync with sibling tutorial -->
We are not yet there and need one more thing to do before we can run it: We need to "target" the Gardener landscape resp. Gardener API server where you have created your shoot cluster (not to be confused with your shoot cluster API server). If you do not know what this is or how to download the Gardener API server `kubeconfig`, please follow [these instructions](https://github.com/gardener/dashboard/blob/master/docs/usage/project-operations.md#prerequisites). You can either download your *personal* credentials or *project* credentials (see [creation of a `serviceaccount`](https://github.com/gardener/dashboard/blob/master/docs/usage/gardener-api.md#prerequisites)) to interact with Gardener. For now (fastest and most convenient way, but generally not recommended), let's use your *personal* credentials, but if you later plan to automate your experiments, please use proper *project* credentials (a `serviceaccount` is not bound to your person, but to the project, and can be restricted using [RBAC roles and role bindings](https://kubernetes.io/docs/reference/access-authn-authz/rbac), which is why we recommend this for production).

To download your *personal* credentials, open the Gardener Dashboard and click on your avatar in the upper right corner of the page. Click "My Account", then look for the "Access" pane, then "Kubeconfig", then press the "Download" button and save the `kubeconfig` to disk. Run the following command next:

``` sh
export KUBECONFIG=path/to/kubeconfig
```
<!-- END of section that must be kept in sync with sibling tutorial -->

We are now set and you can run your script:

``` sh
python path/to/script.py
```

You should see output like this (depends on cloud provider):

``` txt
[Info] Installing signal handlers to terminate all active background threads on involuntary signals (note that SIGKILL cannot be handled).
[Info] Validating client credentials and listing probably impacted instances and/or networks with the given arguments zone='world-1a' and filters={'instances': [{'Name': 'tag-key', 'Values': ['kubernetes.io/cluster/shoot--my-project--my-shoot']}], 'vpcs': [{'Name': 'tag-key', 'Values': ['kubernetes.io/cluster/shoot--my-project--my-shoot']}]}:
[Info] 1 instance(s) would be impacted:
[Info] - i-aabbccddeeff0000
[Info] 1 VPC(s) would be impacted:
[Info] - vpc-aabbccddeeff0000
[Info] Validating client credentials and listing probably impacted instances and/or networks with the given arguments zone='world-1b' and filters={'instances': [{'Name': 'tag-key', 'Values': ['kubernetes.io/cluster/shoot--my-project--my-shoot']}], 'vpcs': [{'Name': 'tag-key', 'Values': ['kubernetes.io/cluster/shoot--my-project--my-shoot']}]}:
[Info] 1 instance(s) would be impacted:
[Info] - i-aabbccddeeff0001
[Info] 1 VPC(s) would be impacted:
[Info] - vpc-aabbccddeeff0000
Please confirm running a (double) zone outage against the above resources.
Press `Y` to continue...
[Info] Launching background thread run_cloud_provider_network_failure_simulation.
[Info] Launching background thread run_cloud_provider_network_failure_simulation.
[Info] Partitioning VPCs matching [{'Name': 'tag-key', 'Values': ['kubernetes.io/cluster/shoot--my-project--my-shoot']}] in zone world-1a (total).
[Info] Partitioning VPCs matching [{'Name': 'tag-key', 'Values': ['kubernetes.io/cluster/shoot--my-project--my-shoot']}] in zone world-1b (total).
[Info] Created blocking network access control list acl-aabbccddeeff0000.
[Info] Created blocking network access control list acl-aabbccddeeff0001.
[Info] ...
[Info] Time is up for run_cloud_provider_network_failure_simulation at 12:01:00 (60.2s net duration). Terminating now.
[Info] Unpartitioning VPCs matching [{'Name': 'tag-key', 'Values': ['kubernetes.io/cluster/shoot--my-project--my-shoot']}] in zone world-1b (total).
[Info] ...
[Info] Deleted blocking network access control list acl-aabbccddeeff0001.
[Info] Time is up for run_cloud_provider_network_failure_simulation at 12:02:00 (120.3s net duration). Terminating now.
[Info] Unpartitioning VPCs matching [{'Name': 'tag-key', 'Values': ['kubernetes.io/cluster/shoot--my-project--my-shoot']}] in zone world-1a (total).
[Info] ...
[Info] Deleted blocking network access control list acl-aabbccddeeff0000.
```

🎉 Congratulations! You successfully ran your first `chaosgarden` script.

You can see how both failure simulations were launched in parallel and how one finished at `12:01:00` (`~1m` net duration) while the other finished at `12:02:00` (`~2m` net duration). If you watched your workload in parallel, you should have seen the effect. Depending on your [node monitor grace period](https://kubernetes.io/docs/concepts/architecture/nodes/#condition) you may have also seen the nodes transition to `NotReady` and back again.

<!-- BEGIN of section that must be kept in sync with sibling tutorial -->
## High Availability

Developing highly available workload that can tolerate a zone outage is no trivial task. You can find more information on how to achieve this goal in our [best practices guide on high availability](https://github.com/gardener/gardener/blob/master/docs/usage/high-availability/shoot_high_availability_best_practices.md).

Thank you for your interest in Gardener chaos engineering and making your workload more resilient.

## Further Reading

Here some links for further reading:

- **Examples**: [Experiments](experiments), [Scripts](scripts)
- **Gardener Chaos Engineering**: [GitHub](https://github.com/gardener/chaos-engineering), [PyPI](https://pypi.org/project/chaosgarden), [Module Docs for Gardener Users](https://github.com/gardener/chaos-engineering/tree/main/docs/garden)
- **Chaos Toolkit Core**: [Home Page](https://chaostoolkit.org), [Installation](https://chaostoolkit.org/reference/usage/install), [Concepts](https://chaostoolkit.org/reference/concepts), [GitHub](https://github.com/chaostoolkit/chaostoolkit)
<!-- END of section that must be kept in sync with sibling tutorial -->
