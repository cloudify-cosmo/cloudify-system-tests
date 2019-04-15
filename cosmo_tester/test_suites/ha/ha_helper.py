########
# Copyright (c) 2017 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.

import os
import time
import fabric.network

from requests.exceptions import ConnectionError
from cloudify_rest_client.exceptions import CloudifyClientError


def wait_nodes_online(cfy, managers, logger):
    """Wait until all of the cluster nodes are online"""
    def _all_nodes_online(nodes):
        result = cfy.cluster.status()
        index, count = 0, 0
        while index < len(result):
            index = result.find('Active', index)
            if index == -1:
                break
            count += 1
        if count == len(nodes):
            return True
    logger.info('Waiting for all nodes to be online...')
    _wait_cluster_status(_all_nodes_online, managers, logger)


def _wait_cluster_status(predicate, managers, logger, timeout=150,
                         poll_interval=1):
    """Wait until the cluster is in a state decided by predicate

    :param predicate: a function deciding if the cluster is in the desired
                      state, when passed in the list of nodes
    :param managers: a list of managers that will be polled for status
    :type managers: list of _CloudifyManager
    :param logger: The logger to use
    :param timeout: How long to wait for leader election
    :param poll_interval: Interval to wait between requests
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        for manager in managers:
            try:
                nodes = manager.client.manager.get_managers().items
                if predicate(nodes):
                    return
            except (ConnectionError, CloudifyClientError):
                logger.debug('_wait_cluster_status: manager {0} did not '
                             'respond'.format(manager))

        logger.debug('_wait_cluster_status: none of the nodes responded')
        time.sleep(poll_interval)

    raise RuntimeError('Timeout when waiting for cluster status')


def delete_active_profile():
    active_profile_path = os.path.join(os.environ['CFY_WORKDIR'],
                                       '.cloudify/active.profile')
    if os.path.exists(active_profile_path):
        os.remove(active_profile_path)


def _set_test_user(cfy, manager, logger, username, userpass, tenant_name):
    manager.use()
    logger.info('Using manager `{0}`'.format(manager.ip_address))
    cfy.profiles.set('-u', username, '-p', userpass, '-t', tenant_name)


def toggle_cluster_node(manager, service, logger, disable=True):
    """
    Disable or enable a manager to avoid it from being picked as the leader
    during tests
    """
    action_msg, action = \
        ("Shutting down", 'stop') if disable else ("Starting", 'start')
    with manager.ssh() as fabric:
        logger.info('{0} {1} service on manager {2}'.format(
            action_msg, service, manager.ip_address))
        fabric.run('sudo systemctl {0} {1}'.format(action, service))


def reverse_cluster_test(cluster_machines, logger):
    for manager in cluster_machines.instances:
        toggle_cluster_node(manager, 'nginx', logger, disable=False)


def failover_cluster(cfy, distributed_installation,
                     distributed_ha_hello_worlds, logger):
    """Test that the cluster fails over in case of a service failure

    - stop nginx on leader
    - check that a new leader is elected
    - stop mgmtworker on that new leader, and restart nginx on the former
    - check that the original leader was elected
    """
    cfy.cluster.update_profile()
    remaining_active_node = distributed_installation.instances[-1]
    # stop nginx on all nodes except last - force choosing the last as the
    # leader (because only the last one has services running)
    for manager in distributed_installation.instances[:-1]:
        logger.info('Simulating manager %s REST failure by stopping'
                    ' nginx service', manager.ip_address)
        toggle_cluster_node(manager, 'nginx', logger)

    # Making sure ClusterHTTPClient works properly
    cfy.cluster.status()

    _test_hellos(distributed_ha_hello_worlds)

    new_remaining_active_node = distributed_installation.instances[0]
    # force going back to the original active manager - start nginx on it, and
    # stop nginx on the current active manager (simulating failure)
    toggle_cluster_node(new_remaining_active_node, 'nginx',
                        logger, disable=False)
    logger.info('Simulating manager %s REST failure by stopping '
                'nginx service', remaining_active_node.ip_address)
    toggle_cluster_node(remaining_active_node, 'nginx', logger,
                        disable=True)

    cfy.cluster.status()

    _test_hellos(distributed_ha_hello_worlds, delete_blueprint=True)


def fail_and_recover_cluster(cfy, distributed_installation, logger):
    def _iptables(manager, block_nodes, flag='-A'):
        with manager.ssh() as _fabric:
            for other_host in block_nodes:
                _fabric.sudo('iptables {0} INPUT -s {1} -j DROP'
                             .format(flag, other_host.private_ip_address))
                _fabric.sudo('iptables {0} OUTPUT -d {1} -j DROP'
                             .format(flag, other_host.private_ip_address))
        fabric.network.disconnect_all()

    victim_manager = distributed_installation.instances[0]

    logger.info('Simulating network failure that isolates a manager')
    _iptables(victim_manager, distributed_installation.instances[1:])

    cfy.cluster.status()

    logger.info('End of simulated network failure')
    _iptables(victim_manager, distributed_installation.instances[1:],
              flag='-D')

    wait_nodes_online(cfy, distributed_installation.instances, logger)


def _test_hellos(hello_worlds, install=False, delete_blueprint=False):
    for hello_world in hello_worlds:
        if delete_blueprint:
            hello_world.delete_blueprint()
            continue
        hello_world.upload_blueprint()
        if install:
            hello_world.create_deployment()
            hello_world.install()
