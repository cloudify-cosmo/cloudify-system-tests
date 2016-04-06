########
# Copyright (c) 2014 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.

import time

from requests import ConnectionError
from cosmo_tester.framework.util import create_rest_client
from cosmo_tester.test_suites.test_blueprints.hello_world_bash_test import \
    AbstractHelloWorldTest
from cosmo_tester.test_suites.test_marketplace_image_builder\
    .abstract_packer_test import AbstractPackerTest
from cosmo_tester.framework.cfy_helper import CfyHelper


class OpenstackNodecellarTest(AbstractHelloWorldTest, AbstractPackerTest):

    def setUp(self):
        super(OpenstackNodecellarTest, self).setUp()

    def test_nodecellar_single_host(self):
        self.logger.info('TEST')  # TODO: Remove this line
        self.build_with_packer(only='openstack')
        self.deploy_image_openstack()

        self.client = create_rest_client(
            self.openstack_manager_public_ip
        )

        response = {'status': None}
        attempt = 0
        max_attempts = 40
        while response['status'] != 'running':
            attempt += 1
            if attempt >= max_attempts:
                raise RuntimeError('Manager did not start in time')
            else:
                time.sleep(3)
            try:
                response = self.client.manager.get_status()
            except ConnectionError:
                pass

        conf = self.env.cloudify_config

        self.openstack_agents_secgroup = 'system-tests-security-group'
        self.openstack_agents_keypair = conf.get('system-tests-keypair-name',
                                                 'system-tests-keypair')

        self.openstack_nodecellar_test_config_inputs = {
            'user_ssh_key': conf['openstack_ssh_keypair_name'],
            'agents_security_group_name': self.openstack_agents_secgroup,
            'agents_keypair_name': self.openstack_agents_keypair,
            'agents_user': conf.get('openstack_agents_user', 'ubuntu'),
            'openstack_username': conf['keystone_username'],
            'openstack_password': conf['keystone_password'],
            'openstack_auth_url': conf['keystone_url'],
            'openstack_tenant_name': conf['keystone_tenant_name'],
            'openstack_region': conf['region'],
        }

        time.sleep(90)
        # We have to retry this a few times, as even after the manager is
        # accessible we still see failures trying to create deployments
        deployment_created = False
        attempt = 0
        max_attempts = 40
        while not deployment_created:
            attempt += 1
            if attempt >= max_attempts:
                raise RuntimeError('Manager did not start in time')
            else:
                time.sleep(3)
            try:
                self.client.deployments.create(
                    blueprint_id='CloudifySettings',
                    deployment_id='config',
                    inputs=self.openstack_nodecellar_test_config_inputs,
                )
                self.addCleanup(self._delete_agents_secgroup)
                self.addCleanup(self._delete_agents_keypair)
                deployment_created = True
            except Exception as err:
                # TODO: This should be a more specific exception
                if attempt >= max_attempts:
                    raise err

        attempt = 0
        max_attempts = 40
        execution_started = False
        while not execution_started:
            attempt += 1
            if attempt >= max_attempts:
                raise RuntimeError('Manager did not start in time')
            else:
                time.sleep(3)
            try:
                self.client.executions.start(
                    deployment_id='config',
                    workflow_id='install',
                )
                execution_started = True
            except Exception as err:
                # The error is a 'DeploymentEnvironmentCreationPendingError',
                # but catching that doesn't work, so we have to catch all
                # TODO: Figure out what error we really should catch
                if attempt >= max_attempts:
                    raise err

        self.cfy = CfyHelper(management_ip=self.openstack_manager_public_ip)

        self._run(
            inputs={
                'agent_user': 'ubuntu',
                'image': self.env.ubuntu_trusty_image_name,
                'flavor': self.env.flavor_name
            },
            influx_host_ip=self.openstack_manager_public_ip,
        )

    def _delete_agents_keypair(self):
        conn = self._get_conn_openstack()
        keypair = conn.keypairs.find(name=self.openstack_agents_keypair)
        keypair.delete()

    def _delete_agents_secgroup(self):
        conn = self._get_conn_openstack()
        secgroup = conn.security_groups.find(
            name=self.openstack_agents_secgroup
        )
        secgroup.delete()

    def get_public_ip(self, nodes_state):
        return self.openstack_manager_public_ip

    @property
    def expected_nodes_count(self):
        return 4

    @property
    def host_expected_runtime_properties(self):
        return []

    @property
    def entrypoint_node_name(self):
        return 'host'

    @property
    def entrypoint_property_name(self):
        return 'ip'
