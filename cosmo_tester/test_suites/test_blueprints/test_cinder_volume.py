########
# Copyright (c) 2014 GigaSpaces Technologies Ltd. All rights reserved
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

import cosmo_tester.framework.util as util
import os

from cosmo_tester.framework.handlers import openstack as openstack_handler
from cosmo_tester.framework.testenv import TestCase


class CinderVolumeTest(TestCase):

    def test_volume_create_new(self):
        self._test_volume('cinder-volume-create-new.yaml')

    def test_volume_use_existing(self):
        volume_name = 'test-volume'
        cinderclient = openstack_handler.cinder_client(
            self.env.cloudify_config)

        volume = cinderclient.volumes.create(size=1,
                                             display_name=volume_name)

        self._test_volume('cinder-volume-use-existing.yaml')

        cinderclient.volumes.delete(volume.id)

    def _test_volume(self, blueprint):
        self.blueprint_yaml = os.path.join(
            util.get_blueprint_path('openstack'), blueprint)

        before, after = self.upload_deploy_and_execute_install()

        self._post_install_assertions(before, after)

        self.execute_uninstall()

        self._post_uninstall_assertions()

    def _post_install_assertions(self, before_state, after_state):
        delta = self.get_manager_state_delta(before_state, after_state)

        self.assertEqual(len(delta['deployment_nodes']), 1)

        self.assertEqual(len(delta['node_state']), 1)

        self._check_nodes(delta)
        self._check_blueprint(delta)
        self._check_deployment(delta)

        nodes_state = delta['node_state'].values()[0]
        self.assertEqual(len(nodes_state), 2)

        for key, value in nodes_state.items():
            if 'volume' in key:
                self.assertTrue('volume_id' in value['runtime_properties'])
                self.assertTrue('volume_device_name'
                                in value['runtime_properties'])
                self.assertEqual(value['state'], 'started')

    def _post_uninstall_assertions(self):
        nodes_instances = self.client.node_instances.list(self.deployment_id)
        self.assertEqual(len([node_ins for node_ins in nodes_instances if
                              node_ins.state != 'deleted']), 0)

    def _check_nodes(self, delta):
        self.assertEqual(len(delta['nodes']), 2)
        deployment = delta['deployments'].values()[0]
        nodes = self.client.nodes.list(deployment.id)
        self.assertEqual(len(nodes), 2)
        for node in nodes:
            if node.id == 'test_volume':
                self.assertEqual(len(node.relationships), 1)

    def _check_blueprint(self, delta):
        self.assertEqual(len(delta['blueprints']), 1)

    def _check_deployment(self, delta):
        self.assertEqual(len(delta['deployments']), 1)
        deployment_from_list = delta['deployments'].values()[0]
        deployment = self.client.deployments.get(deployment_from_list.id)
        self.assertEqual(deployment_from_list.id, deployment.id)
        self.deployment_id = deployment_from_list.id
        self._check_executions(deployment)

    def _check_executions(self, deployment):
        executions = self.client.deployments.list_executions(deployment.id)

        self.assertEqual(len(executions), 2)

        execution_from_list = executions[0]
        execution_by_id = self.client.executions.get(execution_from_list.id)

        self.assertEqual(execution_from_list.id, execution_by_id.id)
        self.assertEqual(execution_from_list.workflow_id,
                         execution_by_id.workflow_id)
        self.assertEqual(execution_from_list['blueprint_id'],
                         execution_by_id['blueprint_id'])

        events, total_events = self.client.events.get(execution_by_id.id)

        self.assertGreater(len(events), 0)
