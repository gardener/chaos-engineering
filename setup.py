import os

import setuptools

own_dir = os.path.abspath(os.path.dirname(__file__))


def version():
    with open(os.path.join(own_dir, 'VERSION')) as file:
        return file.read().strip()


def readme():
    with open(os.path.join(own_dir, 'README.md'), encoding='utf-8') as file:
        return file.read()


def packages():
    return setuptools.find_packages()


def modules():
    return [os.path.basename(os.path.splitext(module)[0]) for module in os.scandir(path = own_dir) if module.is_file() and module.name.endswith('.py')]


def requirements():
    with open(os.path.join(own_dir, 'requirements.txt')) as file:
        for line in file.readlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            yield line


setuptools.setup(
    # https://setuptools.pypa.io/en/latest/userguide/declarative_config.html#metadata
    name                          = 'chaosgarden',
    version                       = version(),
    url                           = 'https://github.com/gardener/chaos-engineering',
    author                        = 'SAP SE',
    license                       = 'License :: OSI Approved :: Apache Software License', # https://pypi.org/classifiers
    description                   = 'Generic cloud provider zone outage and Kubernetes pod disruption simulations with specific support for Gardener',
    long_description              = 'This package provides generic [`chaostoolkit`](https://chaostoolkit.org) modules to simulate *compute* and *network* outages for various cloud providers as well as *pod disruptions* for any Kubernetes cluster.\n\n' +
                                    '<img src="https://raw.githubusercontent.com/gardener/gardener/master/logo/gardener.svg" width="16"/> [Gardener](https://github.com/gardener/gardener) users benefit from an additional module that leverages the generic modules, but exposes their functionality in the most simple, homogeneous, and secure way (no need to specify cloud provider credentials, cluster credentials, or filters explicitly; retrieves credentials and stores them in memory only).\n\n' +
                                    'Please check out the repo [README](https://github.com/gardener/chaos-engineering/blob/main/readme.md) for more information and then head out to our [getting started tutorial](https://github.com/gardener/chaos-engineering/blob/main/docs/tutorials/getting_started.md) and/or [Python scripting tutorial](https://github.com/gardener/chaos-engineering/blob/main/docs/tutorials/python_scripting.md), if you want to see what it is like to work with the `chaosgarden` package.',
    long_description_content_type = 'text/markdown',
    keywords                      = ['chaostoolkit', 'kubernetes', 'gardener'],

    # https://setuptools.pypa.io/en/latest/userguide/declarative_config.html#options
    platforms                     = ['AWS', 'Azure', 'GCP', 'OpenStack', 'vSphere', 'Kubernetes', 'Gardener'],
    install_requires              = list(requirements()),
    python_requires               = '>= 3.9',
    entry_points                  = {},
    packages                      = packages(),
    package_data                  = {'chaosgarden.k8s.probe.resources': ['templated_resources.yaml']},
    py_modules                    = modules()
)
