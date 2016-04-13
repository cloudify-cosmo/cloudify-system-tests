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
from cloudify_rest_client.exceptions import CloudifyClientError
from cosmo_tester.framework.util import create_rest_client
from cosmo_tester.test_suites.test_blueprints.hello_world_bash_test import \
    AbstractHelloWorldTest
from cosmo_tester.test_suites.test_marketplace_image_builder\
    .abstract_packer_test import AbstractPackerTest
from cosmo_tester.framework.cfy_helper import CfyHelper


class AWSHelloWorldTest(AbstractHelloWorldTest, AbstractPackerTest):

    def setUp(self):
        super(AWSHelloWorldTest, self).setUp()

    def test_hello_world_openstack(self):
        self.build_with_packer(only='aws')
        self.deploy_image_aws()

        self.client = create_rest_client(
            self.aws_manager_public_ip
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
            except CloudifyClientError:
                # Manager not fully ready
                pass
            except ConnectionError:
                # Timeout
                pass

        conf = self.env.cloudify_config

        self.aws_agents_secgroup = 'marketplace-system-tests-security-group'
        self.aws_agents_keypair = conf.get('system-tests-keypair-name',
                                           'marketplace-system-tests-keypair')

        self.aws_hello_world_test_config_inputs = {
            'user_ssh_key': conf['aws_ssh_keypair_name'],
            'agents_security_group_name': self.aws_agents_secgroup,
            'agents_keypair_name': self.aws_agents_keypair,
            'agents_user': conf.get('aws_agents_user', 'ubuntu'),
            'aws_access_key': conf['aws_access_key'],
            'aws_secret_key': conf['aws_secret_key'],
        }

        # Arbitrary sleep to wait for manager to actually finish starting as
        # otherwise we suffer timeouts in the next section
        # TODO: This would be better if it actually had some way of checking
        # the manager was fully up and we had a reasonable upper bound on how
        # long we should expect to wait for that
        time.sleep(90)

        # We have to retry this a few times, as even after the manager is
        # accessible we still see failures trying to create deployments
        deployment_created = False
        attempt = 0
        max_attempts = 40
        while not deployment_created:
            attempt += 1
            if attempt >= max_attempts:
                raise RuntimeError('Manager not created in time')
            else:
                time.sleep(3)
            try:
                self.client.deployments.create(
                    blueprint_id='CloudifySettings',
                    deployment_id='config',
                    inputs=self.aws_hello_world_test_config_inputs,
                )
                self.addCleanup(self._delete_agents_secgroup)
                self.addCleanup(self._delete_agents_keypair)
                deployment_created = True
            except Exception as err:
                if attempt >= max_attempts:
                    raise err
                else:
                    self.logger.warn(
                        'Saw error {}. Retrying.'.format(str(err))
                    )

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
                if attempt >= max_attempts:
                    raise err
                else:
                    self.logger.warn(
                        'Saw error {}. Retrying.'.format(str(err))
                    )

        self.cfy = CfyHelper(management_ip=self.aws_manager_public_ip)

        time.sleep(120)

        self._run(
            blueprint_file='ec2-vpc-blueprint.yaml',
            inputs={
                'agent_user': 'ubuntu',
                'image_id': conf['aws_trusty_image_id'],
                'vpc_id': conf['aws_vpc_id'],
                'vpc_subnet_id': conf['aws_subnet_id'],
            },
            influx_host_ip=self.aws_manager_public_ip,
        )

    def _delete_agents_keypair(self):
        conn = self._get_conn_aws()
        conn.delete_key_pair(key_name=self.aws_agents_keypair)

    def _delete_agents_secgroup(self):
        conn = self._get_conn_aws()
        sgs = conn.get_all_security_groups()
        candidate_sgs = [
            sg for sg in sgs
            if sg.name == self.aws_agents_secgroup
            and sg.vpc_id == self.env.cloudify_config['aws_vpc_id']
        ]
        if len(candidate_sgs) != 1:
            raise RuntimeError('Could not clean up agents security group')
        else:
            sg_id = candidate_sgs[0].id
            for sg in sgs:
                for rule in sg.rules:
                    groups = [grant.group_id for grant in rule.grants]
                    if sg_id in groups:
                        self._delete_sg_rule_reference(
                            security_group=sg,
                            proto=rule.ip_protocol,
                            from_port=rule.from_port,
                            to_port=rule.to_port,
                            source_sg=candidate_sgs[0],
                        )
            candidate_sgs[0].delete()

    def _delete_sg_rule_reference(self,
                                  security_group,
                                  from_port,
                                  to_port,
                                  source_sg,
                                  proto='tcp'):
        security_group.revoke(
            ip_protocol=proto,
            from_port=from_port,
            to_port=to_port,
            src_group=source_sg,
        )

    def get_public_ip(self, nodes_state):
        return self.aws_manager_public_ip

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
