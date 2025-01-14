# **Module: `azure`**

## Purpose

### What?

This module provides [`chaostoolkit`](https://chaostoolkit.org) actions to simulate zone outages in Azure. It supports:

- **Compute**: *Termination* or *hard restart/reboot* of virtual machines in one zone with a min/max lifetime (e.g. 0s-0s to shoot down any machine right when it tries to come up or e.g. 10-60s to let them come up at least for 10s but shoot them down at the latest after 60s).
- **Network**: Blocking only *ingress* or only *egress* or *all* network traffic for virtual machines in one zone.

:warning: If you block network traffic one way, e.g. *ingress* (resp. *egress*), the other way, then *egress* (resp. *ingress*), is fully opened, so use with care.

You can run the above in parallel, even of the same type, as long as the targeted zones differ. This way you can also test whether you recover after a multi-zonal outage.

### How?

- **Compute**: Based on the given zone and filters, virtual machines are identified busily/continuously and *terminated* or *hard restarted/rebooted*. You may provide a min/max lifetime to make the process more random, chaotic, and unpredictable, which may further help you unearth issues.
- **Network**: Based on the given zone and filters, virtual machine network interface cards are identified busily/continuously and associated with a blocking network security group, blocking either only *ingress* or *egress* or *all* network traffic. This operation must be rolled back when completed.

### Why?

Developing highly available workload that can tolerate a zone outage is no trivial task. You can find more information on how to achieve this goal [here](https://github.com/gardener/gardener/blob/master/docs/usage/high-availability/shoot_high_availability_best_practices.md). To put your solution to the test, this module will help you.

## Usage

### Actions and Rollbacks

`chaostoolkit` introduces so-called [actions](https://chaostoolkit.org/reference/api/experiment/#action) that can be composed into [experiments](https://chaostoolkit.org/reference/api/experiment/#experiment) that perform operations against a system (here Azure). The following actions (and explicit [rollbacks](https://chaostoolkit.org/reference/api/experiment/#rollbacks)) are supported:

Module: [`chaosgarden.azure.actions`](/chaosgarden/azure/actions.py)

- `assess_filters_impact`: Show which virtual machines would be affected by the given zone and filters. Useful in combination with [wait-for](/docs/human/readme.md) before launching the actual action.
- `run_compute_failure_simulation`: Run compute failure simulation.
- `run_compute_failure_simulation_in_background`: Same as above, but running in background as a thread. Normally not used with experiments, but directly in Python (scripts).
- `run_network_failure_simulation`: Run network failure simulation.
- `rollback_network_failure_simulation`: Rollback network failure simulation explicitly (usually performed automatically above, but can also be invoked explicitly as rollback step in an experiment to deal with interruptions).
- `run_network_failure_simulation_in_background`: Same as above, but running in background as a thread. Normally not used with experiments, but directly in Python (scripts).

### Cloud Provider Filters

Please consult your cloud provider documentation for the exact filter syntax (not interpreted by `chaosgarden`).

### Configuration

The [leveraged upstream open source incubator extension](https://github.com/chaostoolkit-incubator/chaostoolkit-azure/tree/master/chaosazure) requires the following mandatory [configuration](https://chaostoolkit.org/reference/api/experiment/#configuration) fields:

- `azure_region`: Region
- `azure_subscription_id`: Subscription id
- `azure_resource_group`: Resource group

### Secrets

The [leveraged upstream open source incubator extension](https://github.com/chaostoolkit-incubator/chaostoolkit-azure/tree/master/chaosazure) requires the following mandatory [secret](https://chaostoolkit.org/reference/api/experiment/#secrets) fields:

- `azure_cloud`: Cloud name, usually `AZURE_PUBLIC_CLOUD`
- `client_id`: Client id
- `client_secret`: Client secret
- `tenant_id`: Tenant id

The above mentioned extension also supports other parameters like `access_token`, but those were not tested.

## Examples

- [Assess Filters Impact](/docs/azure/assess-filters-impact.json)
- [Run Compute Failure Simulation](/docs/azure/run-compute-failure-simulation.json)
- [Run Network Failure Simulation](/docs/azure/run-network-failure-simulation.json)
