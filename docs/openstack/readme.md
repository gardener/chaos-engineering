# **Module: `openstack`**

## Purpose

### What?

This module provides [`chaostoolkit`](https://chaostoolkit.org) actions to simulate zone outages in OpenStack. It supports:

- **Compute**: *Termination* or *hard restart/reboot* of servers in one zone with a min/max lifetime (e.g. 0s-0s to shoot down any machine right when it tries to come up or e.g. 10-60s to let them come up at least for 10s but shoot them down at the latest after 60s).
- **Network**: Blocking only *ingress* or only *egress* or *all* network traffic for servers in one zone.

:warning: If you block network traffic one way, e.g. *ingress* (resp. *egress*), the other way, then *egress* (resp. *ingress*), is fully opened, so use with care.

You can run the above in parallel, even of the same type, as long as the targeted zones differ. This way you can also test whether you recover after a multi-zonal outage.

### How?

- **Compute**: Based on the given zone and filters, servers are identified busily/continuously and *terminated* or *hard restarted/rebooted*. You may provide a min/max lifetime to make the process more random, chaotic, and unpredictable, which may further help you unearth issues.
- **Network**: Based on the given zone and filters, servers are identified busily/continuously and temporarily disassociated from the current and re-associated with a blocking security group, blocking either only *ingress* or *egress* or *all* network traffic. This operation must be rolled back when completed.

### Why?

Implementing high availability that can even tolerate a zone outage unscathed is no trivial task. You can find more information on how to achieve this goal [here](/docs/garden/high-availability.md). To put your solution to the test, this module will help you.

## Usage

### Actions and Rollbacks

`chaostoolkit` introduces so-called [actions](https://chaostoolkit.org/reference/api/experiment/#action) that can be composed into [experiments](https://chaostoolkit.org/reference/api/experiment/#experiment) that perform operations against a system (here OpenStack). The following actions (and explicit [rollbacks](https://chaostoolkit.org/reference/api/experiment/#rollbacks)) are supported:

Module: [`chaosgarden.openstack.actions`](/chaosgarden/openstack/actions.py)

- `assess_filters_impact`: Show which servers would be affected by the given zone and filters. Useful in combination with [wait-for](/docs/human/readme.md) before launching the actual action.
- `run_compute_failure_simulation`: Run compute failure simulation.
- `run_compute_failure_simulation_in_background`: Same as above, but running in background as a thread. Normally not used with experiments, but directly in Python (scripts).
- `run_network_failure_simulation`: Run network failure simulation.
- `rollback_network_failure_simulation`: Rollback network failure simulation explicitly (usually performed automatically above, but can also be invoked explicitly as rollback step in an experiment to deal with interruptions).
- `run_network_failure_simulation_in_background`: Same as above, but running in background as a thread. Normally not used with experiments, but directly in Python (scripts).

### Cloud Provider Filters

Please consult your cloud provider documentation for the exact filter syntax (not interpreted by `chaosgarden`).

### Configuration

The [upstream open source incubator extension](https://github.com/chaostoolkit-incubator/chaostoolkit-openstack/tree/master/chaosopenstack) isn't directly used (insufficient functionality) and instead the [OpenStack SDK](https://opendev.org/openstack/openstacksdk/src/branch/master/openstack/connection.py) is directly used and requires the following mandatory [configuration](https://chaostoolkit.org/reference/api/experiment/#configuration) fields:

- `openstack_region`: Region

### Secrets

The [upstream open source incubator extension](https://github.com/chaostoolkit-incubator/chaostoolkit-openstack/tree/master/chaosopenstack) isn't directly used (insufficient functionality) and instead the [OpenStack SDK](https://opendev.org/openstack/openstacksdk/src/branch/master/openstack/connection.py) is directly used and requires the following mandatory [secret](https://chaostoolkit.org/reference/api/experiment/#secrets) fields:

- `auth_url`: Authentication Keystone URL
- `user_domain_name`: Domain name for user
- `username`: User name
- `password`: User password
- `project_domain_name`: Domain name for project
- `project_name`: Project name

The above mentioned OpenStack SDK probably also supports other parameters, but those were not tested.

## Examples

- [Assess Filters Impact](/docs/openstack/assess-filters-impact.json)
- [Run Compute Failure Simulation](/docs/openstack/run-compute-failure-simulation.json)
- [Run Network Failure Simulation](/docs/openstack/run-network-failure-simulation.json)
