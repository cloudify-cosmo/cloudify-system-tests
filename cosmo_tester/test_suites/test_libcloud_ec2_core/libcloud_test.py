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

import unittest
from cosmo_tester.framework.ec2_testenv import TestCase, bootstrap, teardown
from cloudify_rest_client import CloudifyClient
from cosmo_tester.framework.ec2_api import (get_sg_list_names,
                                            get_key_pair_name_list,
                                            get_not_terminated_node_name_list)


class LibcloudTest(TestCase):

    def setUp(self, *args, **kwargs):
        bootstrap()
        super(LibcloudTest, self).setUp(*args, **kwargs)

    def test_libcloud(self):
        name_prefix = self.env.cloudify_config['cloudify']['resources_prefix']\
            if 'resources_prefix' in self.env.cloudify_config['cloudify']\
            else ''
        self._validate_provisioned(name_prefix)
        self._validate_cloudify_manager()
        self._test_blueprint()
        teardown()
        self._validate_teardowned()

    def _test_blueprint(self):
        blueprint_path = self.copy_blueprint('libcloud')
        self.blueprint_yaml = blueprint_path / 'blueprint.yaml'

        self.cfy.upload_blueprint(
            blueprint_id=self.test_id,
            blueprint_path=self.blueprint_yaml)

        self.cfy.create_deployment(
            blueprint_id=self.test_id,
            deployment_id=self.test_id)
        install_workers = self.client.deployments.list_executions(
            deployment_id=self.test_id)[0]
        self.logger.info('Waiting for install workers workflow to terminate')
        self.wait_for_execution(install_workers, timeout=120)

        execution = self.client.deployments.execute(deployment_id=self.test_id,
                                                    workflow_id='install')
        self.logger.info('Waiting for install workflow to terminate')
        self.wait_for_execution(execution, timeout=600)
        self.logger.info('All done!')

    def _validate_provisioned(self, name_prefix):
        networking_config = self.env.cloudify_config['networking']
        self._validate_networking(networking_config, name_prefix)
        compute_config = self.env.cloudify_config['compute']
        self._validate_compute(compute_config, name_prefix)

    def _validate_cloudify_manager(self):
        client = CloudifyClient(self.env.management_ip)
        self.assertIsNotNone(client.manager.get_status(),
                             '')

    def _validate_networking(self, networking_config, name_prefix):
        created = get_sg_list_names(self.env.cloudify_config)
        self.assertIn(
            name_prefix + networking_config['agents_security_group']['name'],
            created,
            'ERROR: Agents security group wasn\'t created')
        self.assertIn(
            name_prefix + networking_config['management_security_group'][
                'name'],
            created,
            'ERROR: Management security group wasn\'t created')
        created_len = len(created)
        self.assertEqual(
            created_len,
            2,
            'ERROR: Two security groups should be created'
            ' but created {0}: {1}'.format(created_len, ', '.join(created)))

    def _validate_key_pairs(self, compute_config, name_prefix):
        created_names = get_key_pair_name_list(self.env.cloudify_config)
        self.assertIn(
            name_prefix + compute_config['management_server'][
                'management_keypair']['name'],
            created_names,
            'ERROR: Management key pair wasn\'t created')
        self.assertIn(
            name_prefix + compute_config['agent_servers']['agents_keypair'][
                'name'],
            created_names,
            'ERROR: Agents key pair wasn\'t created')
        created_len = len(created_names)
        self.assertEqual(
            created_len,
            2,
            'ERROR: Two key pairs should be created'
            ' but created {0}: {1}'
            .format(created_len, ', '.join(created_names)))

    def _validate_management_server(self, management_config, name_prefix):
        created, created_names =\
            get_not_terminated_node_name_list(self.env.cloudify_config)
        self.assertIn(
            name_prefix + management_config['instance']['name'],
            created_names,
            'ERROR: Management server wasn\'t created')
        created_len = len(created_names)
        self.assertEqual(
            created_len,
            1,
            'ERROR: The only one management server should be created'
            ' but created {0}: {1}'
            .format(created_len, ', '.join(created_names)))
        node = created[0]
        required_image = management_config['instance']['image']
        provided_image = node.extra['image_id']
        self.assertEqual(
            provided_image,
            required_image,
            'ERROR: Created management server wrong image:'
            ' required - {0}, provided - {1}'
            .format(required_image, provided_image))
        required_size = management_config['instance']['size']
        provided_size = node.extra['instance_type']
        self.assertEqual(
            provided_size,
            required_size,
            'ERROR: Created management server wrong size:'
            ' required - {0}, provided - {1}'
            .format(required_size, provided_size))

    def _validate_compute(self, compute_config, name_prefix):
        self._validate_key_pairs(compute_config, name_prefix)
        management_config = compute_config['management_server']
        self._validate_management_server(management_config, name_prefix)

    def _validate_teardowned(self):
        created = get_sg_list_names(self.env.cloudify_config)
        self.assertEqual(
            len(created),
            0,
            'ERROR: Not all created security groups were deleted'
            ' during teardown process: ' + ', '.join(created))
        created_names = get_key_pair_name_list(self.env.cloudify_config)
        self.assertEqual(
            len(created_names),
            0,
            'ERROR: Not all created key pairs were deleted'
            ' during teardown process: ' + ', '.join(created))
        created, created_names =\
            get_not_terminated_node_name_list(self.env.cloudify_config)
        self.assertEqual(
            len(created_names),
            0,
            'ERROR: Not all created nodes were deleted'
            ' during teardown process: ' + ', '.join(created_names))
