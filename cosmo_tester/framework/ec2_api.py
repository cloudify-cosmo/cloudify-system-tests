__author__ = 'Oleksandr_Raskosov'

import copy
import time

from libcloud.compute.types import Provider
from libcloud.compute.providers import get_driver
from libcloud.compute.types import NodeState
import libcloud.security


libcloud.security.VERIFY_SSL_CERT = False


TIMEOUT = 3000

driver = None


def _get_provider(provider_name):
        if provider_name == Provider.EC2_AP_NORTHEAST:
            return Provider.EC2_AP_NORTHEAST
        elif provider_name == Provider.EC2_AP_SOUTHEAST:
            return Provider.EC2_AP_SOUTHEAST
        elif provider_name == Provider.EC2_AP_SOUTHEAST2:
            return Provider.EC2_AP_SOUTHEAST2
        elif provider_name == Provider.EC2_EU:
            return Provider.EC2_EU
        elif provider_name == Provider.EC2_EU_WEST:
            return Provider.EC2_EU_WEST
        elif provider_name == Provider.EC2_SA_EAST:
            return Provider.EC2_SA_EAST
        elif provider_name == Provider.EC2_US_EAST:
            return Provider.EC2_US_EAST
        elif provider_name == Provider.EC2_US_WEST:
            return Provider.EC2_US_WEST
        elif provider_name == Provider.EC2_US_WEST_OREGON:
            return Provider.EC2_US_WEST_OREGON


def _get_driver(provider_name, access_id, secret_key):
    provider = _get_provider(provider_name)
    global driver
    if not driver:
        driver = get_driver(provider)(access_id, secret_key)
    return driver


def ec2_infra_state(cloudify_config):
    """
    @retry decorator is used because this error sometimes occur:
    ConnectionFailed: Connection to neutron failed: Maximum attempts reached
    """
    driver = _get_driver(cloudify_config['connection']['cloud_provider_name'],
                         cloudify_config['connection']['access_id'],
                         cloudify_config['connection']['secret_key'])
    return {
        'security_groups': dict(_security_groups(driver)),
        'key_pairs': dict(_key_pairs(driver)),
        'public_ips': dict(_public_ips(driver)),
        'nodes': dict(_nodes(driver))
    }


def ec2_infra_state_delta(before, after):
    after = copy.deepcopy(after)
    return {
        prop: _remove_keys(after[prop], before[prop].keys())
        for prop in before.keys()
    }


def remove_ec2_resources(cloudify_config, resources_to_remove):
    driver = _get_driver(cloudify_config['connection']['cloud_provider_name'],
                         cloudify_config['connection']['access_id'],
                         cloudify_config['connection']['secret_key'])

    nodes = driver.list_nodes()
    public_ips = driver.ex_describe_all_addresses()
    security_groups = driver.ex_get_security_groups()
    key_pairs = driver.list_key_pairs()

    for node in nodes:
        if node.id in resources_to_remove['nodes']:
            driver.destroy_node(node)
            timeout = TIMEOUT
            while node.state is not NodeState.TERMINATED:
                timeout -= 5
                if timeout <= 0:
                    raise RuntimeError('Node failed to terminate {0} in time'
                                       .format(NodeState.TERMINATED))
                time.sleep(5)
                node = driver.list_nodes(ex_node_ids=[node.id])[0]

    for public_ip in public_ips:
        if public_ip.ip in resources_to_remove['public_ips']:
            driver.ex_disassociate_address(public_ip)
            driver.ex_release_address(public_ip)

    sg_to_delete = []
    for sg in security_groups:
        if sg.id in resources_to_remove['security_groups']:
            _remove_sg_rules(sg, driver)
            sg_to_delete.append(sg)
    for sg in sg_to_delete:
        driver.ex_delete_security_group_by_id(sg.id)

    for key in key_pairs:
        if key.name in resources_to_remove['key_pairs']:
            driver.delete_key_pair(key)


def _security_groups(driver):
    return [(n.id, n.name)
            for n in driver.ex_get_security_groups()]


def _key_pairs(driver):
    return [(n.name, n.name)
            for n in driver.list_key_pairs()]


def _public_ips(driver):
    return [(n, n)
            for n in driver.ex_describe_all_addresses()]


def _nodes(driver):
    return [(n.id, n.name)
            for n in driver.list_nodes()]


def _remove_keys(dct, keys):
    for key in keys:
        if key in dct:
            del dct[key]
    return dct


def _remove_sg_rules(sg, driver):
    for rule in sg.ingress_rules:
        for pair in rule['group_pairs']:
            if ('group_id' in pair) and ('group_name' in pair):
                pair['group_name'] = ''
        driver.ex_revoke_security_group_ingress(
            id=sg.id,
            from_port=rule['from_port'],
            to_port=rule['to_port'],
            group_pairs=rule['group_pairs'],
            cidr_ips=rule['cidr_ips'])
    for rule in sg.egress_rules:
        for pair in rule['group_pairs']:
            if ('group_id' in pair) and ('group_name' in pair):
                pair['group_name'] = ''
        driver.ex_revoke_security_group_egress(
            id=sg.id,
            from_port=rule['from_port'],
            to_port=rule['to_port'],
            group_pairs=rule['group_pairs'],
            cidr_ips=rule['cidr_ips'])


# def get_sg_list_names(driver):
#     created = []
#     groups = self.driver.sg_controller.list()
#     prfx = self.name_prefix
#     for group in groups:
#         if group.startswith(prfx):
#             created.append(group)
#     return created
#
#
# def get_key_pair_list_w_names(driver):
#     created = []
#     created_names = []
#     keys = self.driver.keypair_controller.list()
#     prfx = self.name_prefix
#     for key in keys:
#         name = key.name
#         if name.startswith(prfx):
#             created.append(key)
#             created_names.append(name)
#     return created, created_names
#
#
# def get_node_list_w_names(driver, not_in_state=None):
#     created = []
#     created_names = []
#     nodes = self.driver.server_controller.list()
#     prfx = self.name_prefix
#     for node in nodes:
#         name = node.name
#         if name.startswith(prfx):
#             if not_in_state:
#                 if not_in_state != node.state:
#                     created.append(node)
#                     created_names.append(name)
#             else:
#                 created.append(node)
#                 created_names.append(name)
#     return created, created_names
