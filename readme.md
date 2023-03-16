# Chaos Engineering Tools for Gardener-Managed Clusters

[![reuse compliant](https://reuse.software/badge/reuse-compliant.svg)](https://reuse.software/)

## Introduction

This package provides [Gardener](https://github.com/gardener/gardener)-independent [`chaostoolkit`](https://chaostoolkit.org) modules to simulate *compute* and *network* outages for various cloud providers as well as to *disrupt pods* in Kubernetes clusters.

<img src="https://github.com/gardener/gardener/blob/master/logo/gardener.svg" width="16"/> [Gardener](https://github.com/gardener/gardener) users benefit from an [*additional* module](#gardener) that leverages the generic modules, but hides the configuration differences from the end user (no need to specify cloud provider or cluster credentials, filters and everything else is computed automatically).

### Cloud Providers

Read more on how to simulate *compute* and *network* outages for these cloud providers here:

- **Module: `alicloud`** (Alibaba Cloud is not yet supported)
- **Module: [`aws`](/docs/aws/readme.md)**
- **Module: [`azure`](/docs/azure/readme.md)**
- **Module: [`gcp`](/docs/gcp/readme.md)**
- **Module: [`openstack`](/docs/openstack/readme.md)**
- **Module: [`vsphere`](/docs/vsphere/readme.md)**
- **Module: `metal`** (Gardener on Metal is not yet supported)

The API, parameterization, and implementation is as homogeneous as possible across the different cloud providers, so that consumers of these packages have only minimal effort. However, if you are a Gardener user, please read on and use the [Gardener-specific module](#gardener) instead, which makes it even easier and safer for you.

### Kubernetes

Read more on how to *disrupt pods* here:

- **Module: [`k8s`](/docs/k8s/readme.md)**

The module supports powerful filter criteria like node labels, pod labels, pod metadata like kind or name, or pod owner reference. However, if you are a Gardener user, please read on and use the [Gardener-specific module](#gardener) instead, which makes it even easier and safer for you.

### Gardener

Whether you want to target cloud provider resources or pods, if you have a Gardener-managed cluster, this package is for you as it supports all of the above, but in the most homogeneous way (no need to specify cloud provider or cluster credentials, filters and everything else is computed automatically):

- **Module: [`garden`](/docs/garden/readme.md)**

### Human Interactions

Finally, there is a tiny additional module that is primarily useful for human invocation of `chaostoolkit` experiments (e.g. first assess the would-be impacted machines, wait for human user confirmation, then actually start the zone outage):

- **Module: [`human`](/docs/human/readme.md)**

## Installation, Usage, and Configuration

This package was developed and tested with Python 3.9+. It's not yet available on [PyPI](https://pypi.org), but this is planned eventually. For now, you will have to clone this repository and add it to your `PYTHONPATH`. You may want to [create a virtual environment](https://packaging.python.org/en/latest/guides/installing-using-pip-and-virtual-environments/#creating-a-virtual-environment) before installing the requirements with `pip`.

``` sh
git clone https://github.com/gardener/chaos-engineering gardener-chaos-engineering
cd gardener-chaos-engineering
python -m pip install -r requirements.txt
export PYTHONPATH="$PYTHONPATH:$(pwd)"
```

If you want to use the VMware vSphere module, please note the remarks in [`requirements.txt`](/requirements.txt) for `vSphere`.

For usage and configuration of the individual modules, please see the detailed [docs](/docs) on the modules listed above.

This package is based on [`chaostoolkit`](https://chaostoolkit.org) and their incubation extensions for the different infrastructures. That said, it can be used also directly in Python, but if you intend to use it in combination with the [`chaostoolkit`](https://chaostoolkit.org) [CLI](https://chaostoolkit.org/reference/usage/cli) and [experiments](https://chaostoolkit.org/reference/api/experiment), you will have to install it and make yourself familiar with it. Here some pointers/further reading:

- **Chaos Toolkit Core**: [Home Page](https://chaostoolkit.org), [Installation](https://chaostoolkit.org/reference/usage/install), [Concepts](https://chaostoolkit.org/reference/concepts), [GitHub](https://github.com/chaostoolkit/chaostoolkit)
- **Chaos Toolkit Extensions**:
  - **AWS**: [Docs](https://chaostoolkit.org/drivers/aws), [GitHub](https://github.com/chaostoolkit-incubator/chaostoolkit-aws/tree/master/chaosaws) (many resources)
  - **Azure**: [Docs](https://chaostoolkit.org/drivers/azure), [GitHub](https://github.com/chaostoolkit-incubator/chaostoolkit-azure/tree/master/chaosazure) (some resources)
  - **GCP**: [Docs](https://chaostoolkit.org/drivers/gcp), [GitHub](https://github.com/chaostoolkit-incubator/chaostoolkit-google-cloud-platform/tree/master/chaosgcp) (only GKE node pools)
  - **OpenStack**: [GitHub](https://github.com/chaostoolkit-incubator/chaostoolkit-openstack/tree/master/chaosopenstack) (only compute)
  - **VMware**: [GitHub](https://github.com/chaostoolkit-incubator/chaostoolkit-vmware/tree/master/chaosvmware) (nothing/empty at the time of this writing)
  - **Kubernetes**: [Docs](https://chaostoolkit.org/drivers/kubernetes), [GitHub](https://github.com/chaostoolkit/chaostoolkit-kubernetes/tree/master/chaosk8s) (many resources)

In some cases, we extended the original upstream open source incubator extensions significantly and we may eventually contribute those changes back upstream, if the community is interested.

## Implementing High Availability and Tolerating Zone Outages

Implementing high availability that can even tolerate a zone outage unscathed is no trivial task. You can find more information on how to achieve this goal [here](https://github.com/gardener/gardener/blob/master/docs/usage/shoot_high_availability_best_practices.md). While many recommendations are general enough, the examples are specific in how to achieve this in a Gardener-managed cluster and where/how to tweak the different control plane components. If you do not use Gardener, it may be still a worthwhile read.

Thank you for your interest in Gardener chaos engineering and making your workload more resilient.
