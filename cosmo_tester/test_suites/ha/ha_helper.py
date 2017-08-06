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


import time
import os

from cloudify_rest_client.exceptions import CloudifyClientError


class HighAvailabilityHelper(object):
    @staticmethod
    def set_active(manager, cfy, logger):
        try:
            logger.info('Setting active manager %s',
                        manager.ip_address)
            cfy.cluster('set-active', manager.ip_address)
        except Exception as e:
            logger.info('Setting active manager error message: %s', e.message)
        finally:
            HighAvailabilityHelper.wait_leader_election([manager], logger)

    @staticmethod
    def wait_leader_election(managers, logger, timeout=120, poll_interval=1):
        """Wait until one of managers is elected the leader

        :param managers: a list of managers that will be polled for status
        :type managers: list of _CloudifyManager
        :param logger: The logger to use
        :param timeout: How long to wait for leader election
        :param poll_interval: Interval to wait between requests
        """
        logger.info('Waiting for a leader election...')
        deadline = time.time() + timeout
        while time.time() < deadline:
            for manager in managers:
                try:
                    nodes = manager.client.cluster.nodes.list()
                except CloudifyClientError:
                    logger.debug('wait_leader_election: manager {0} did not '
                                 'respond'.format(manager))
                    nodes = []

                if any(node['master'] for node in nodes):
                    return nodes

            logger.debug('None of the nodes are the leader')
            time.sleep(poll_interval)

        raise RuntimeError('Timeout when waiting for leader election')

    @staticmethod
    def verify_nodes_status(manager, cfy, logger):
        logger.info('Verifying that manager %s is a leader '
                    'and others are replicas', manager.ip_address)
        cfy.cluster.nodes.list()
        nodes = manager.client.cluster.nodes.list()

        for node in nodes:
            if node.name == str(manager.ip_address):
                assert node.master is True
                logger.info('Manager %s is a leader ', node.name)
            else:
                assert node.master is not True
                logger.info('Manager %s is a replica ', node.name)

    @staticmethod
    def delete_active_profile():
        active_profile_path = os.path.join(os.environ['CFY_WORKDIR'],
                                           '.cloudify/active.profile')
        if os.path.exists(active_profile_path):
            os.remove(active_profile_path)
