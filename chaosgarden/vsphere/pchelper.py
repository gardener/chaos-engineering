"""
Property Collector helper module.
"""

import pyVmomi
from pyVmomi import vim


# Shamelessly borrowed from:
# https://github.com/dnaeon/py-vconnector/blob/master/src/vconnector/core.py
def collect_properties(si, view_ref, obj_type, path_set=None,
                       include_mors=False):
    """
    Collect properties for managed objects from a view ref

    Check the vSphere API documentation for example on retrieving
    object properties:

        - http://goo.gl/erbFDz

    Args:
        si          (ServiceInstance): ServiceInstance connection
        view_ref (pyVmomi.vim.view.*): Starting point of inventory navigation
        obj_type      (pyVmomi.vim.*): Type of managed object
        path_set               (list): List of properties to retrieve
        include_mors           (bool): If True include the managed objects
                                       refs in the result

    Returns:
        A list of properties for the managed objects

    """
    collector = si.content.propertyCollector

    # Create object specification to define the starting point of
    # inventory navigation
    obj_spec = pyVmomi.vmodl.query.PropertyCollector.ObjectSpec()
    obj_spec.obj = view_ref
    obj_spec.skip = True

    # Create a traversal specification to identify the path for collection
    traversal_spec = pyVmomi.vmodl.query.PropertyCollector.TraversalSpec()
    traversal_spec.name = 'traverseEntities'
    traversal_spec.path = 'view'
    traversal_spec.skip = False
    traversal_spec.type = view_ref.__class__
    obj_spec.selectSet = [traversal_spec]

    # Identify the properties to the retrieved
    property_spec = pyVmomi.vmodl.query.PropertyCollector.PropertySpec()
    property_spec.type = obj_type

    if not path_set:
        property_spec.all = True

    property_spec.pathSet = path_set

    # Add the object and property specification to the
    # property filter specification
    filter_spec = pyVmomi.vmodl.query.PropertyCollector.FilterSpec()
    filter_spec.objectSet = [obj_spec]
    filter_spec.propSet = [property_spec]

    # Retrieve properties
    props = collector.RetrieveContents([filter_spec])

    data = []
    for obj in props:
        properties = {}
        for prop in obj.propSet:
            properties[prop.name] = prop.val

        if include_mors:
            properties['obj'] = obj.obj

        data.append(properties)
    return data


def get_container_view(si, obj_type, container=None):
    """
    Get a vSphere Container View reference to all objects of type 'obj_type'

    It is up to the caller to take care of destroying the View when no longer
    needed.

    Args:
        obj_type (list): A list of managed object types

    Returns:
        A container view ref to the discovered managed objects
    """
    if not container:
        container = si.content.rootFolder

    view_ref = si.content.viewManager.CreateContainerView(
        container=container,
        type=obj_type,
        recursive=True
    )
    return view_ref


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