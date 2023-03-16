# Chaos Engineering Tools for Gardener-Managed Clusters

[![reuse compliant](https://reuse.software/badge/reuse-compliant.svg)](https://reuse.software/)

## Introduction

This package provides [Gardener](https://github.com/gardener/gardener)-independent [`chaostoolkit`](https://chaostoolkit.org) modules to simulate *compute* and *network* outages for various cloud providers as well as *pod disruptions* in any Kubernetes cluster.

<img src="https://raw.githubusercontent.com/gardener/gardener/master/logo/gardener.svg" width="16"/> [Gardener](https://github.com/gardener/gardener) users benefit from an [*additional* module](#gardener) that leverages the generic modules, but exposes their functionality in the most simple, homogeneous, and secure way (no need to specify cloud provider credentials, cluster credentials, or filters explicitly; retrieves credentials and stores them in memory only):

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

Whether you want to target cloud provider resources or pods, if you have a Gardener-managed cluster, this package is for you as it supports all of the above, but in the most simple, homogeneous, and secure way (no need to specify cloud provider credentials, cluster credentials, or filters explicitly; retrieves credentials and stores them in memory only):

- **Module: [`garden`](/docs/garden/readme.md)**

### Human Interactions

Finally, there is a tiny additional module that is primarily useful for human invocation of `chaostoolkit` experiments (e.g. first assess the would-be impacted machines, wait for human user confirmation, then actually start the zone outage):

- **Module: [`human`](/docs/human/readme.md)**

## Installation, Usage, and Configuration

This package was developed and tested with Python 3.9+ and is being published to [PyPI](https://pypi.org/project/chaosgarden). You may want to [create a virtual environment](https://packaging.python.org/en/latest/guides/installing-using-pip-and-virtual-environments/#creating-a-virtual-environment) before installing it with `pip`.

``` sh
pip install chaosgarden
```

If you want to use the [VMware vSphere module](/docs/vsphere/readme.md), please note the remarks in [`requirements.txt`](/requirements.txt) for `vSphere`. Those are not contained in the published [PyPI](https://pypi.org/project/chaosgarden) package.

For usage and configuration of the individual modules, please see the detailed [docs](/docs) on the modules listed above.

This package is based on [`chaostoolkit`](https://chaostoolkit.org) and to some degree also on some of its incubation extensions (requirements included within the `chaosgarden` package). It can also be used directly from Python scripts and supports this mode with additional convenience that helps launch actions and probes in background, so that you can compose also complex scenarios with ease.

If you intend to use it in combination with the [`chaostoolkit`](https://chaostoolkit.org) [CLI](https://chaostoolkit.org/reference/usage/cli) and [experiment files](https://chaostoolkit.org/reference/api/experiment), you will have to [install the CLI](https://chaostoolkit.org/reference/usage/install/#install-the-cli) first and make yourself familiar with it.

Here some links for further reading:

- **Chaos Toolkit Core**: [Home Page](https://chaostoolkit.org), [Installation](https://chaostoolkit.org/reference/usage/install), [Concepts](https://chaostoolkit.org/reference/concepts), [GitHub](https://github.com/chaostoolkit/chaostoolkit)
- **Chaos Toolkit Extensions**:
  - **AWS**: [Docs](https://chaostoolkit.org/drivers/aws), [GitHub](https://github.com/chaostoolkit-incubator/chaostoolkit-aws/tree/master/chaosaws) (many resources are supported)
  - **Azure**: [Docs](https://chaostoolkit.org/drivers/azure), [GitHub](https://github.com/chaostoolkit-incubator/chaostoolkit-azure/tree/master/chaosazure) (some resources are supported)
  - **GCP**: [Docs](https://chaostoolkit.org/drivers/gcp), [GitHub](https://github.com/chaostoolkit-incubator/chaostoolkit-google-cloud-platform/tree/master/chaosgcp) (only GKE node pools are supported)
  - **OpenStack**: [GitHub](https://github.com/chaostoolkit-incubator/chaostoolkit-openstack/tree/master/chaosopenstack) (only compute resources are supported)
  - **VMware**: [GitHub](https://github.com/chaostoolkit-incubator/chaostoolkit-vmware/tree/master/chaosvmware) (nothing/empty at the time of this writing)
  - **Kubernetes**: [Docs](https://chaostoolkit.org/drivers/kubernetes), [GitHub](https://github.com/chaostoolkit/chaostoolkit-kubernetes/tree/master/chaosk8s) (many resources are supported)

In some cases, we extended the original upstream open source incubator extensions significantly and we may eventually contribute those changes back upstream, if the community is interested.

## Implementing High Availability and Tolerating Zone Outages

Implementing high availability that can even tolerate a zone outage unscathed is no trivial task. You can find more information on how to achieve this goal [here](https://github.com/gardener/gardener/blob/master/docs/usage/shoot_high_availability_best_practices.md). While many recommendations are general enough, the examples are specific in how to achieve this in a Gardener-managed cluster and where/how to tweak the different control plane components. If you do not use Gardener, it may be still a worthwhile read.

Thank you for your interest in Gardener chaos engineering and making your workload more resilient.
