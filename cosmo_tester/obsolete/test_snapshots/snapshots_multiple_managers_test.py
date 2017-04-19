########
# Copyright (c) 2015 GigaSpaces Technologies Ltd. All rights reserved
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
import random
import shutil
import string

from cloudify_rest_client.exceptions import CloudifyClientError

from cosmo_tester.framework.testenv import bootstrap, teardown
from cosmo_tester.framework.util import create_rest_client, \
    YamlPatcher, get_cfy
from cosmo_tester.test_suites.test_blueprints.hello_world_bash_test import (
    HelloWorldBashTest)


def setUp():
    bootstrap()


def tearDown():
    teardown()


class TwoManagersTest(HelloWorldBashTest):
    """
    This test bootstraps managers, installs helloworld using the first manager,
    checks whether it has been installed correctly, creates a snapshot,
    downloads it, uploads it to the second manager, uninstalls helloworld using
    the second manager, checks whether helloworld is not running indeed and
    tears down those managers.
    """

    def setUp(self):
        super(TwoManagersTest, self).setUp()

        self.cfy2 = get_cfy()
        second_manager_blueprint_path = '{}_existing'.format(
            self.env._manager_blueprint_path)

        shutil.copy2(self.env._manager_blueprint_path,
                     second_manager_blueprint_path)

        external_resources = [
            'node_templates.management_network.properties',
            'node_templates.management_subnet.properties',
            'node_templates.router.properties',
            'node_templates.agents_security_group.properties',
            'node_templates.management_security_group.properties',
        ]

        with YamlPatcher(second_manager_blueprint_path) as patch:
            for prop in external_resources:
                patch.merge_obj(prop, {'use_external_resource': True})

        second_cloudify_config_path = '{}_existing'.format(
            self.env.cloudify_config_path)

        shutil.copy2(self.env.cloudify_config_path,
                     second_cloudify_config_path)

        new_resources = ['manager_server_name', 'manager_port_name']

        with YamlPatcher(second_cloudify_config_path) as patch:
            for prop in new_resources:
                patch.append_value(prop, '2')

        self.cfy2.bootstrap(
            second_manager_blueprint_path,
            inputs=second_cloudify_config_path,
            install_plugins=self.env.install_plugins,
            keep_up_on_failure=False,
            task_retries=5,
            verbose=False
        )

        # Bootstrap updates the active profile, so get_manager_ip returns
        # the IP of the second manager
        self.client2 = create_rest_client(self.get_manager_ip())

    def _start_execution_and_wait(self, client, deployment, workflow_id):
        execution = client.executions.start(deployment, workflow_id)
        self.wait_for_execution(execution, self.default_timeout, client)

    def _create_snapshot(self, client, name):
        execution = client.snapshots.create(name, False, False)
        self.wait_for_execution(execution, self.default_timeout, client)

    def _restore_snapshot(self, client, name):
        execution = client.snapshots.restore(name, True)
        self.wait_for_execution(execution, self.default_timeout, client)

    def _do_post_install_assertions(self):
        context = super(TwoManagersTest, self)._do_post_install_assertions()
        self.logger.info('Creating snapshot...')
        self._create_snapshot(self.client, self.test_id)
        try:
            self.client.snapshots.get(self.test_id)
        except CloudifyClientError as e:
            self.fail(e.message)
        self.logger.info('Snapshot created.')

        self.logger.info('Downloading snapshot...')
        snapshot_file_name = ''.join(random.choice(string.ascii_letters)
                                     for _ in xrange(10))
        snapshot_file_path = os.path.join('/tmp', snapshot_file_name)
        self.client.snapshots.download(self.test_id, snapshot_file_path)
        self.logger.info('Snapshot downloaded.')

        self.logger.info('Uploading snapshot to the second manager...')
        self.client2.snapshots.upload(snapshot_file_path, self.test_id)

        try:
            uploaded_snapshot = self.client2.snapshots.get(
                self.test_id)
            self.assertEqual(
                uploaded_snapshot.status,
                'uploaded',
                "Snapshot {} has a wrong status: '{}' instead of 'uploaded'."
                .format(self.test_id, uploaded_snapshot.status)
            )
        except CloudifyClientError as e:
            self.fail(e.message)
        self.logger.info('Snapshot uploaded.')

        self.logger.info('Removing snapshot file...')
        if os.path.isfile(snapshot_file_path):
            os.remove(snapshot_file_path)
        self.logger.info('Snapshot file removed.')

        self.logger.info('Restoring snapshot...')
        self._restore_snapshot(self.client2, self.test_id)
        try:
            self.client2.deployments.get(self.test_id)
        except CloudifyClientError as e:
            self.fail(e.message)
        self.logger.info('Snapshot restored.')

        self.logger.info('Installing new agents...')
        self._start_execution_and_wait(self.client2, self.test_id,
                                       'install_new_agents')
        self.logger.info('Installed new agents.')
        return context

    def execute_uninstall(self, deployment_id=None,
                          cfy=None,
                          delete_deployment_and_blueprint=False):
        super(TwoManagersTest, self).execute_uninstall(cfy=self.cfy2)

    def _assert_nodes_deleted(self, client=None):
        super(TwoManagersTest, self)._assert_nodes_deleted(self.client2)

    @property
    def default_timeout(self):
        return 1000
