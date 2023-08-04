
import time
import json

from dataclasses import dataclass, field

from aliyunsdkcore.client import AcsClient
from aliyunsdkcore.acs_exception.exceptions import ClientException
from aliyunsdkcore.acs_exception.exceptions import ServerException
from aliyunsdkcore.request import AcsRequest

from aliyunsdkecs.request.v20140526.DescribeInstancesRequest import DescribeInstancesRequest
from aliyunsdkecs.request.v20140526.RebootInstanceRequest import RebootInstanceRequest
from aliyunsdkecs.request.v20140526.DeleteInstanceRequest import DeleteInstanceRequest

from aliyunsdkecs.request.v20140526.ListTagResourcesRequest import ListTagResourcesRequest as EcsListTagResourcesRequest

from aliyunsdkvpc.request.v20160428.DescribeVpcsRequest import DescribeVpcsRequest
from aliyunsdkvpc.request.v20160428.DescribeVSwitchesRequest import DescribeVSwitchesRequest
from aliyunsdkvpc.request.v20160428.DescribeNetworkAclsRequest import DescribeNetworkAclsRequest
from aliyunsdkvpc.request.v20160428.CreateNetworkAclRequest import CreateNetworkAclRequest
from aliyunsdkvpc.request.v20160428.DeleteNetworkAclRequest import DeleteNetworkAclRequest
from aliyunsdkvpc.request.v20160428.AssociateNetworkAclRequest import AssociateNetworkAclRequest
from aliyunsdkvpc.request.v20160428.UnassociateNetworkAclRequest import UnassociateNetworkAclRequest
from aliyunsdkvpc.request.v20160428.UpdateNetworkAclEntriesRequest import UpdateNetworkAclEntriesRequest
from aliyunsdkvpc.request.v20160428.TagResourcesRequest import TagResourcesRequest as VpcTagResourcesRequest
from aliyunsdkvpc.request.v20160428.UnTagResourcesRequest import UnTagResourcesRequest as VpcUnTagResourcesRequest
from aliyunsdkvpc.request.v20160428.ListTagResourcesRequest import ListTagResourcesRequest as VpcListTagResourcesRequest


def string_array_equal(sorce_array, dest_array):
    if not isinstance(sorce_array,list) or not isinstance(dest_array,list):
        return False
    if len(sorce_array) != len(dest_array):
        return False
    for idx in range(len(sorce_array)):
        if sorce_array[idx] != dest_array[idx]:
            return False
    return True

def remove_dict_key(the_dict, key_name):
    if the_dict and key_name in the_dict:
        del the_dict[key_name]

MAX_RETRY=5
MAX_SIZE = 50
@dataclass
class AliyunBot:
    region: str
    access_key: str
    secret_key: str
    client: AcsClient = field(init=False)

    def __post_init__(self):    
        self.client = AcsClient(self.access_key, self.secret_key, self.region)

    def __clean_request(self, the_request: AcsRequest):
        params = the_request.get_query_params()
        remove_dict_key(params, 'Version')
        remove_dict_key(params, 'Action')
        remove_dict_key(params, 'Format')
        remove_dict_key(params, 'RegionId')
        remove_dict_key(params, 'AccessKeyId')
        remove_dict_key(params, 'Timestamp')
        remove_dict_key(params, 'SignatureMethod')
        remove_dict_key(params, 'SignatureVersion')
        remove_dict_key(params, 'SignatureNonce')
        remove_dict_key(params, 'Signature')

    def __send_request(self, request):
        try_count = 0
        while True:
            try:
                try_count = try_count +1
                self.__clean_request(request)
                return self.__call_request_action(request)
                
            except ServerException as se:
                
                print(f'error info: {se}')
                if se.get_error_code() in ['Throttling.User'] and try_count < MAX_RETRY:
                    sleep_time = 30 if try_count==1 else 3
                    time.sleep( sleep_time )
                else:
                    print(f'call api failed')
                    return None                
            except Exception as e:
                print(f'call api failed: {e}')
                return None
        return None

    def __call_request_action(self, request):
        request.set_accept_format('json')
        response_str = self.client.do_action_with_exception(request)
        response_str = response_str.decode()
        response_detail = json.loads(response_str)

        return response_detail
      



    def __describe_vpcs(self, VpcName=None, VpcId=None):
        request = DescribeVpcsRequest()
        if VpcName:
            request.set_VpcName(VpcName)
        if VpcId:
            request.set_VpcId(VpcId)
        request.set_PageSize(MAX_SIZE)
        data_list = []
        cur_page = 1
        if resp := self.__send_request(request):
            TotalCount = resp['TotalCount']
            if TotalCount > 0:
                data_list.extend(resp['Vpcs']['Vpc'])
            while len(data_list) < TotalCount:
                cur_page = cur_page + 1
                request.set_PageNumber(cur_page)
                resp = self.__send_request(request)
                data_list.extend(resp['Vpcs']['Vpc'])
        else:
            return None
        return data_list
        
    def __describe_instances(self, VpcId=None, InsId=None):
        request = DescribeInstancesRequest()
        if VpcId:
            request.set_VpcId(VpcId)
        if InsId:
            request.set_InstanceIds([InsId])
        request.set_PageSize(MAX_SIZE)
        data_list = []
        cur_page = 1
        if resp := self.__send_request(request):
            TotalCount = resp['TotalCount']
            if TotalCount > 0:
                data_list.extend(resp['Instances']['Instance'])
            while len(data_list) < TotalCount:
                cur_page = cur_page + 1
                request.set_PageNumber(cur_page)
                resp = self.__send_request(request)
                data_list.extend(resp['Instances']['Instance'])
        else:
            return None
        return data_list

    def __form_instance_data(self, base_instance):
            tag_list = base_instance['Tags']['Tag'] if 'Tags' in base_instance else []
            instance_data = {
                    'AllData':      base_instance,
                    'HostName':     base_instance['HostName'],
                    'InstanceId':   base_instance['InstanceId'],
                    'Status':       base_instance['Status'],
                    'RegionId':     base_instance['RegionId'],
                    'ZoneId':       base_instance['ZoneId'],
                    'VpcId':        base_instance['VpcAttributes']['VpcId'],
                    'Tags': { tag['TagKey']: tag['TagValue'] for tag in tag_list}
                }
            return instance_data
            


    def get_instance(self, InstId):
        the_list = self.__describe_instances(InsId=InstId)
        if the_list is None:
            return None, 'call api fail' 
        if len(the_list) ==1:
            instance_data = self.__form_instance_data(the_list[0]) 
            return instance_data, None
        return None, None 


    def list_instances(self, VpcId):
        the_list = self.__describe_instances(VpcId=VpcId)
        if the_list is None:
            return None, 'call api fail'
        instance_list = [self.__form_instance_data(instance) for instance in the_list]
        
        return instance_list, None

    def get_vpc(self, VpcName=None, VpcId=None):
        the_list = self.__describe_vpcs(VpcName=VpcName, VpcId=VpcId)
        if the_list is None:
            return None, 'call api fail'
        if len(the_list) == 1:
            return the_list[0], None
        return None, None



    def __delete_instance(self, InstId):
        request = DeleteInstanceRequest()
        request.set_InstanceId(InstId)
        request.set_Force(True)
        return self.__send_request(request) is not None  

    def __reboot_instance(self, InstId):
        request = RebootInstanceRequest()
        request.set_InstanceId(InstId)
        return self.__send_request(request) is not None  


    def delete_instance(self, InstId, wait_to_delete=False):
        instance, err = self.get_instance(InstId)
        if err:
            return False
        if instance is None:
            return True
        
        status = instance['Status']

        count = 0
        delete_ok = False
        while count < 3 :
            count += 1
            if self.__delete_instance(InstId):
                delete_ok = True
                break
            time.sleep(2)
        if not delete_ok:
            return False

        if not wait_to_delete:
            return True
        count = 0        
        while count < 30:
            time.sleep(3)
            instance, err = self.get_instance(InstId)
            if err:
                return False
            if instance is None:
                return True
            count += 1
        return False



    def reboot_instance(self, InstId, wait_to_running=False):
        instance, err = self.get_instance(InstId)
        if err:
            return False
        
        status = instance['Status']
        if status not in ['Running']:
            return False
        if status == 'Running':
            count = 0
            reboot_ok = False
            while count < 3 :
                count += 1
                if self.__reboot_instance(InstId):
                    reboot_ok = True
                    break
                time.sleep(2)
            if not reboot_ok:
                return False

        if not wait_to_running:
            return True
        count = 0        
        while count < 30:
            time.sleep(3)
            instance, err = self.get_instance(InstId)
            if err:
                return False
            status = instance['Status']
            if status == 'Running':
                return True
            count += 1
        return False



# tag = {
#     'Key': 'test-key',
#     'Value': 'test-value'
# }
    def __list_ecs_tag_resources(self, resourceType, tag_list=[]):
        if len(tag_list) < 1:
            return None
        
        request = EcsListTagResourcesRequest()
        
        request.set_ResourceType(resourceType)
        request.set_Tags(tag_list)
        data_list = []
        while True:
            if resp := self.__send_request(request):
                data_list.extend(resp['TagResources']['TagResource'])
                NextToken = resp.get('NextToken') or ''
                if NextToken != '':
                    request.set_NextToken(resp['NextToken'])
                else:
                    break
            else:
                return None
        return data_list          

    def list_instance_with_tag(self, tag_list):

        the_list = self.__list_ecs_tag_resources('instance', tag_list)
        if the_list is None:
            return None, 'call api fail'
        instance_list = []
        for ins in the_list:
            ins_id = ins['ResourceId']
            the_instance, err = self.get_instance(ins_id)
            if the_instance:
                instance_list.append(the_instance)
        return instance_list, None

    def __describe_vswitch(self, VSwitchId=None, VpcId=None, ZoneId=None):
        request = DescribeVSwitchesRequest()
        if VSwitchId:
            request.set_VSwitchId(VSwitchId)
        if VpcId:
            request.set_VpcId(VpcId)
        if ZoneId:
            request.set_ZoneId(ZoneId)
        request.set_PageSize(MAX_SIZE)
        data_list = []
        cur_page = 1
        if resp := self.__send_request(request):
            TotalCount = resp['TotalCount']
            if TotalCount > 0:
                data_list.extend(resp['VSwitches']['VSwitch'])
            while len(data_list) < TotalCount:
                cur_page = cur_page + 1
                request.set_PageNumber(cur_page)
                resp = self.__send_request(request)
                data_list.extend(resp['VSwitches']['VSwitch'])
        else:
            return None
        return data_list



    def __form_vswitch_data(self, base_data):
            tag_list = base_data['Tags']['Tag'] if 'Tags' in base_data else []
            form_data = {
                    'AllData':      base_data,
                    'VSwitchId':    base_data['VSwitchId'],
                    'VpcId':        base_data['VpcId'],
                    'ZoneId':       base_data['ZoneId'],
                    'VSwitchName':  base_data['VSwitchName'],
                    'Status':       base_data['Status'],
                    'NetworkAclId': base_data.get('NetworkAclId') or '_NA_',
                    'Tags': { tag['Key']: tag['Value'] for tag in tag_list}
                }
            return form_data
            


    def get_vswitch(self, VSwitchId):
        the_list = self.__describe_vswitch(VSwitchId=VSwitchId)
        if the_list is None:
            return None, 'call api fail' 
        if len(the_list) ==1:
            vswitch_data = self.__form_vswitch_data(the_list[0]) 
            return vswitch_data, None
        return None, None 


    def list_vswitches(self, VpcId=None, ZoneId=None):
        the_list = self.__describe_vswitch(VpcId=VpcId, ZoneId=ZoneId)
        if the_list is None:
            return None, 'call api fail'
        vswitch_list = [self.__form_vswitch_data(vswitch) for vswitch in the_list]
        
        return vswitch_list, None


    def __describe_network_acl(self, AclId=None, VpcId=None, AclName=None):
        request = DescribeNetworkAclsRequest()
        if AclId:
            request.set_NetworkAclId(AclId)
        if VpcId:
            request.set_VpcId(VpcId)
        if AclName:
            request.set_NetworkAclName(AclName)
        request.set_PageSize(MAX_SIZE)
        data_list = []
        cur_page = 1
        if resp := self.__send_request(request):
            TotalCount = resp['TotalCount']
            if TotalCount > 0:
                data_list.extend(resp['NetworkAcls']['NetworkAcl'])
            while len(data_list) < TotalCount:
                cur_page = cur_page + 1
                request.set_PageNumber(cur_page)
                resp = self.__send_request(request)
                data_list.extend(resp['NetworkAcls']['NetworkAcl'])
        else:
            return None
        return data_list


    def __form_alc_entry_list(self, AclEntries, entry_type):
        if entry_type == 'egress':
            return [f'{entry["DestinationCidrIp"]}-{entry["Protocol"]}-{entry["Port"]}-{entry["Policy"]}' for entry in AclEntries]
        if entry_type == 'ingress':
            return [f'{entry["SourceCidrIp"]}-{entry["Protocol"]}-{entry["Port"]}-{entry["Policy"]}' for entry in AclEntries]

    def __form_alc_data(self, base_data):
            tag_list = base_data['Tags']['Tag'] if 'Tags' in base_data else []
            bing_resource_list = base_data['Resources']['Resource']
            EgressAclEntries = base_data['EgressAclEntries']['EgressAclEntry']
            IngressAclEntries = base_data['IngressAclEntries']['IngressAclEntry']

            form_data = {
                    'AllData':      base_data,
                    'NetworkAclId':    base_data['NetworkAclId'],
                    'VpcId':        base_data['VpcId'],
                    'NetworkAclName':  base_data['NetworkAclName'],
                    'Status':       base_data['Status'],
                    'EgressAclEntries': self.__form_alc_entry_list(EgressAclEntries, 'egress'),
                    'IngressAclEntries': self.__form_alc_entry_list(IngressAclEntries, 'ingress'),
                    'BindVswitches': { bind['ResourceId']: bind['Status'] for bind in bing_resource_list},
                    'Tags': { tag['Key']: tag['Value'] for tag in tag_list}
                }
            return form_data


    def get_network_acl(self, AclId):
        the_list = self.__describe_network_acl(AclId=AclId)
        if the_list is None:
            return None, 'call api fail' 
        if len(the_list) ==1:
            vswitch_data = self.__form_alc_data(the_list[0]) 
            return vswitch_data, None
        return None, None
    
    def list_network_acl_by_name(self, AclName):
        the_list = self.__describe_network_acl(AclName=AclName)
        if the_list is None:
            return None, 'call api fail'
        acl_list = [self.__form_alc_data(acl) for acl in the_list]
        return acl_list, None

    def __create_network_acl(self, VpcId, AclName=None):
        request = CreateNetworkAclRequest()
        if AclName:
            request.set_NetworkAclName(AclName)
        request.set_VpcId(VpcId)

        if resp := self.__send_request(request):
            NetworkAclId = resp['NetworkAclId']
            return NetworkAclId
        return None
    
    def create_network_acl(self, VpcId, AclName=None, wait_to_Available=False):
        acl_id = self.__create_network_acl(VpcId, AclName)
        if acl_id is None:
            return None, 'call api fail'
        if wait_to_Available:
            count = 0
            while count < 5:
                time.sleep(3)

                acl, err = self.get_network_acl(AclId=acl_id)
                if err:
                    return acl_id, 'call get acl fail'
                if acl is None:
                    continue
                if acl['Status'] == 'Available':
                    return acl_id, None
                count += 1
            return acl_id, 'create acl time out'
        else:
            return acl_id, None

    def __delete_network_acl(self, AclId):
        request = DeleteNetworkAclRequest()
        request.set_NetworkAclId(AclId)
        return self.__send_request(request) is not None

    def delete_network_acl(self, AclId, wait_to_delete=False):
        acl, err = self.get_network_acl(AclId=AclId)
        if err:
            return False
        if acl is None :
            return True
        if not self.__delete_network_acl(AclId=AclId):
            return False
        
        if not wait_to_delete:
            return True

        count = 0        
        while count < 5:
            time.sleep(3)
            acl, err = self.get_network_acl(AclId=AclId)
            if err:
                return False
            if acl is None:
                return True
            count += 1
        return False


# EgressAclEntry = {
#     'DestinationCidrIp':   '0.0.0.0/0',
#     'Policy':   'drop',  # 'accept' 'drop'
#     'Port':     '-1/-1', # '1/200' '80/80'
#     'Protocol': 'all',  # 'all' 'icmp' 'gre' 'tcp' 'udp' 
# }
# IngressAclEntry = {
#     'SourceCidrIp':   '0.0.0.0/0',
#     'Policy':   'drop',  # 'accept' 'drop'
#     'Port':     '-1/-1', # '1/200' '80/80'
#     'Protocol': 'all',  # 'all' 'icmp' 'gre' 'tcp' 'udp' 
# }

    def __update_network_acl_entries(self, AclId, EgressAclEntry_list=[], IngressAclEntry_list=[]):
        request = UpdateNetworkAclEntriesRequest()
        request.set_NetworkAclId(AclId)
        if len(EgressAclEntry_list) > 0:
            request.set_UpdateEgressAclEntries(True)
            egressAclEntriess = [
                {
                    'DestinationCidrIp': entry.get('DestinationCidrIp') or '0.0.0.0/0',
                    'Policy': entry.get('Policy') or 'accept',
                    'Protocol': entry.get('Protocol') or 'all',
                    'Port': entry.get('Port') or '-1/-1',
                } for entry in EgressAclEntry_list
            ]
            request.set_EgressAclEntriess(egressAclEntriess)
        if len(IngressAclEntry_list) > 0:
            request.set_UpdateIngressAclEntries(True)
            ingressAclEntriess = [
                {
                    'SourceCidrIp': entry.get('SourceCidrIp') or '0.0.0.0/0',
                    'Policy': entry.get('Policy') or 'accept',
                    'Protocol': entry.get('Protocol') or 'all',
                    'Port': entry.get('Port') or '-1/-1',
                } for entry in IngressAclEntry_list
            ]
            request.set_IngressAclEntriess(ingressAclEntriess)

        return self.__send_request(request) is not None


    def update_network_acl_entries(self, AclId, EgressAclEntry_list=[], IngressAclEntry_list=[], check_updated=False):
        acl, err = self.get_network_acl(AclId=AclId)
        if err:
            return False
        if acl is None:
            return False
        need_update = False
        if len(EgressAclEntry_list) > 0:
            egressAclEntry_array = self.__form_alc_entry_list(EgressAclEntry_list, 'egress')
            if not string_array_equal(egressAclEntry_array, acl['EgressAclEntries']):
                need_update = True
        if len(IngressAclEntry_list) > 0:
            ingressAclEntry_array = self.__form_alc_entry_list(IngressAclEntry_list, 'ingress')
            if not string_array_equal(ingressAclEntry_array, acl['IngressAclEntries']):
                need_update = True
        if not need_update:
            return True 
        if not self.__update_network_acl_entries(AclId, EgressAclEntry_list, IngressAclEntry_list):
            return False
        if not check_updated:
            return True
        count = 0        
        while count < 5:
            time.sleep(3)
            acl, err = self.get_network_acl(AclId=AclId)
            if err:
                return False
            if acl['Status'] != 'Available':
                continue   
            entries_same = True
            if len(EgressAclEntry_list) > 0:
                egressAclEntry_array = self.__form_alc_entry_list(EgressAclEntry_list, 'egress')
                if not string_array_equal(egressAclEntry_array, acl['EgressAclEntries']):
                    entries_same = False
            if len(IngressAclEntry_list) > 0:
                ingressAclEntry_array = self.__form_alc_entry_list(IngressAclEntry_list, 'ingress')
                if not string_array_equal(ingressAclEntry_array, acl['IngressAclEntries']):
                    entries_same = False
            if entries_same:
                return True 
            count += 1
        return False        
        
    def __associate_network_acl(self, AclId, VSwitchId):
        request = AssociateNetworkAclRequest()
        request.set_NetworkAclId(AclId)
        request.set_Resources([
            {
                'ResourceType': 'VSwitch',
                'ResourceId': VSwitchId
            }
        ])
        return self.__send_request(request) is not None

    def __unassociate_network_acl(self, AclId, VSwitchId):
        request = UnassociateNetworkAclRequest()
        request.set_NetworkAclId(AclId)
        request.set_Resources([
            {
                'ResourceType': 'VSwitch',
                'ResourceId': VSwitchId
            }
        ])
        return self.__send_request(request) is not None

    def associate_network_acl(self, AclId, VSwitchId, wait_bind=False):
        if AclId =='_NA_':
            return True
        vswitch, err = self.get_vswitch(VSwitchId=VSwitchId)
        if err:
            return False
        if vswitch is None:
            return False
        orginal_acl = vswitch['NetworkAclId']
        if orginal_acl != '_NA_':
            return False
        if orginal_acl == AclId:
            return True

        if not self.__associate_network_acl(AclId, VSwitchId):
            return False
        
        if not wait_bind:
            return True
        count = 0        
        while count < 5:
            time.sleep(3)
            acl, err = self.get_network_acl(AclId=AclId)
            if err:
                return False
            if acl['Status'] != 'Available':
                continue
            bind_status = acl['BindVswitches'].get(VSwitchId) or 'UNBINDED'
            if bind_status == 'BINDED':
                return True
            count += 1
        return False        

        
    def unassociate_network_acl(self, AclId, VSwitchId, wait_unbind=False):
        if AclId == '_NA_':
            return True
        vswitch, err = self.get_vswitch(VSwitchId=VSwitchId)
        if err:
            return False
        if vswitch is None:
            return False
        cur_acl = vswitch['NetworkAclId']
        if cur_acl != AclId:
            return True

        if not self.__unassociate_network_acl(AclId, VSwitchId):
            return False
        
        if not wait_unbind:
            return True
        count = 0        
        while count < 5:
            time.sleep(3)
            acl, err = self.get_network_acl(AclId=AclId)
            if err:
                return False
            if acl['Status'] != 'Available':
                continue
            bind_status = acl['BindVswitches'].get(VSwitchId) or 'UNBINDED'
            if bind_status == 'UNBINDED':
                return True
            count += 1
        return False  

# tag = {
#     'Key': 'test-key',
#     'Value': 'test-value'
# }
    def __tag_vpc_resource(self, resourceType, resourceId, tag_list):
        if len(tag_list) < 1:
            return False
        request = VpcTagResourcesRequest()
        request.set_ResourceType(resourceType)
        request.set_ResourceIds([resourceId])
        request.set_Tags(tag_list)
        return self.__send_request(request) is not None 


    def __untag_vpc_resource(self, resourceType, resourceId, tagKey_list):
        if len(tagKey_list) < 1:
            return False
        request = VpcUnTagResourcesRequest()
        request.set_ResourceType(resourceType)
        request.set_ResourceIds([resourceId])
        request.set_TagKeys(tagKey_list)
        return self.__send_request(request) is not None 


    def tag_vswitch(self, VSwitchId, tag_list):
        if not isinstance(tag_list, list):
            return False
        return self.__tag_vpc_resource('VSWITCH', VSwitchId, tag_list)

    def untag_vswitch(self, VSwitchId, tag_key):
        tagkey_list = [tag_key]

        return self.__untag_vpc_resource('VSWITCH', VSwitchId, tagkey_list)

    def tag_network_acl(self, AclId, tag_list):
        if not isinstance(tag_list, list):
            return False
        return self.__tag_vpc_resource('NETWORKACL', AclId, tag_list) 

    def untag_network_acl(self, AclId, tag_key):
        tagkey_list = [tag_key]

        return self.__untag_vpc_resource('NETWORKACL', AclId, tagkey_list)
          
    def replace_vswitch_acl_bind(self, VSwitchId, AclId):
        vswitch,err = self.get_vswitch(VSwitchId)
        if vswitch is None:
            return False

        original_acl = vswitch['NetworkAclId']
        if AclId == original_acl:
            return True

        if not self.unassociate_network_acl(original_acl, VSwitchId, wait_unbind=True):
            self.associate_network_acl(original_acl, VSwitchId, wait_bind=True)
            return False
        if not self.associate_network_acl(AclId, VSwitchId, wait_bind=True):
            self.unassociate_network_acl(AclId, VSwitchId, wait_unbind=True)
            self.associate_network_acl(original_acl, VSwitchId, wait_bind=True)
            return False
        return True

    def __list_vpc_tag_resources(self, resourceType, tag_list=[]):
        if len(tag_list) < 1:
            return None
        
        request = VpcListTagResourcesRequest()
        
        request.set_ResourceType(resourceType)
        request.set_Tags(tag_list)
        request.set_MaxResults(MAX_SIZE)

        data_list = []
        while True:
            if resp := self.__send_request(request):
                data_list.extend(resp['TagResources']['TagResource'])
                NextToken = resp.get('NextToken') or ''
                if NextToken != '':
                    request.set_NextToken(resp['NextToken'])
                else:
                    break
            else:
                return None
        return data_list   



    def list_network_acl_with_tag(self, tag_list):

        the_list = self.__list_vpc_tag_resources('NETWORKACL', tag_list)
        if the_list is None:
            return None, 'call api fail'
        acl_list = []
        for acl in the_list:
            acl_id = acl['ResourceId']
            the_acl, err = self.get_network_acl(AclId=acl_id)
            if the_acl:
                acl_list.append(the_acl)
        return acl_list, None
            
        