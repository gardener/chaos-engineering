"""
Property Collector helper module.

Modified code from https://github.com/vmware/pyvmomi-community-samples/blob/master/samples/tools/pchelper.py,
especially removing unneeded methods.

Modifications Copyright SAP SE or an SAP affiliate company and Gardener contributors
"""

import pyVmomi
from pyVmomi import vim


def search_for_obj(content, vim_type, name, folder=None, recurse=True):
    """
    Search the managed object for the name and type specified

    Sample Usage:

    get_obj(content, [vim.Datastore], "Datastore Name")
    """
    if folder is None:
        folder = content.rootFolder

    obj = None
    container = content.viewManager.CreateContainerView(folder, vim_type, recurse)

    for managed_object_ref in container.view:
        if managed_object_ref.name == name:
            obj = managed_object_ref
            break
    container.Destroy()
    return obj


def get_all_obj(content, vim_type, folder=None, recurse=True):
    """
    Search the managed object for the name and type specified

    Sample Usage:

    get_obj(content, [vim.Datastore], "Datastore Name")
    """
    if not folder:
        folder = content.rootFolder

    obj = {}
    container = content.viewManager.CreateContainerView(folder, vim_type, recurse)

    for managed_object_ref in container.view:
        obj[managed_object_ref] = managed_object_ref.name

    container.Destroy()
    return obj


def get_obj(content, vim_type, name, folder=None, recurse=True):
    """
    Retrieves the managed object for the name and type specified
    Throws an exception if of not found.

    Sample Usage:

    get_obj(content, [vim.Datastore], "Datastore Name")
    """
    obj = search_for_obj(content, vim_type, name, folder, recurse)
    if not obj:
        raise RuntimeError("Managed Object " + name + " not found.")
    return obj

def search_vms_by_names(si, names):
    """
    Search virtual machine by name
    :param si: A ServiceInstance managed object
    :type name: si
    :param names: A set of virtual machine names
    :type name: set(list(str))
    :returns: A list of virtual machine objects
    :rtype: VirtualMachine
    """
    if not names:
        return []
    return filter_vms(si, lambda vm: vm.name in names)

def filter_vms(si, filter):
    """
    Filter virtual machines
    :param si: A ServiceInstance managed object
    :type name: si
    :param filter: filter function
    :type name: function(vm)->bool
    :returns: A list of virtual machine objects
    :rtype: VirtualMachine
    """
    content = si.content
    root_folder = content.rootFolder
    obj_view = content.viewManager.CreateContainerView(root_folder, [vim.VirtualMachine], True)
    vm_list = obj_view.view
    obj_view.Destroy()
    obj = []
    for vm in vm_list:
        if filter(vm):
            obj.append(vm)
    return obj

def search_resource_pools_by_names(si, names):
    """
    Search resource pools by name
    :param si: A ServiceInstance managed object
    :type name: si
    :param names: A set of resource pool names
    :type name: set(list(str))
    :returns: A list of resource pool objects
    :rtype: ResourcePool
    """
    if not names:
        return []
    return filter_resource_pools(si, lambda p: p.name in names)

def filter_resource_pools(si, filter):
    """
    Filter resource pools
    :param si: A ServiceInstance managed object
    :type name: si
    :param filter: filter function
    :type name: function(pool)->bool
    :returns: A list of resource pool objects
    :rtype: ResourcePool
    """
    content = si.content
    root_folder = content.rootFolder
    obj_view = content.viewManager.CreateContainerView(root_folder, [vim.ResourcePool], True)
    item_list = obj_view.view
    obj_view.Destroy()
    obj = []
    for item in item_list:
        if filter(item):
            obj.append(item)
    return obj

def search_clusters_by_names(si, names):
    """
    Search compute clusters by name
    :param si: A ServiceInstance managed object
    :type name: si
    :param names: A set of compute clusters names
    :type name: set(list(str))
    :returns: A list of compute clusters objects
    :rtype: ClusterComputeResource
    """
    if not names:
        return []
    return filter_clusters(si, lambda p: p.name in names)

def filter_clusters(si, filter):
    """
    Filter compute clusters
    :param si: A ServiceInstance managed object
    :type name: si
    :param filter: filter function
    :type name: function(cluster)->bool
    :returns: A list of compute clusters objects
    :rtype: ClusterComputeResource
    """
    content = si.content
    root_folder = content.rootFolder
    obj_view = content.viewManager.CreateContainerView(root_folder, [vim.ClusterComputeResource], True)
    item_list = obj_view.view
    obj_view.Destroy()
    obj = []
    for item in item_list:
        if filter(item):
            obj.append(item)
    return obj