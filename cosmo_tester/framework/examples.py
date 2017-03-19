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

import json
import os
import re
import testtools
import uuid
from abc import ABCMeta

import pytest
import requests
from fabric import api as fabric_api
from fabric import context_managers as fabric_context_managers
from retrying import retry

from cosmo_tester.framework import git_helper

CLOUDIFY_HELLO_WORLD_EXAMPLE_URL = 'https://github.com/cloudify-cosmo/cloudify-hello-world-example.git'  # noqa


class _AbstractExample(testtools.TestCase):

    __metaclass__ = ABCMeta

    REPOSITORY_URL = None

    def __init__(self, cfy, manager, attributes, ssh_key, logger, tmpdir):
        self.attributes = attributes
        self.logger = logger
        self.manager = manager
        self.cfy = cfy
        self.tmpdir = tmpdir
        self._ssh_key = ssh_key
        self._cleanup_required = False
        self._blueprint_file = None
        self._inputs = None
        self._cloned_to = None
        self.blueprint_id = 'hello-{0}'.format(str(uuid.uuid4()))
        self.deployment_id = self.blueprint_id

    @property
    def blueprint_file(self):
        if not self._blueprint_file:
            raise ValueError('blueprint_file not set')
        return self._blueprint_file

    @blueprint_file.setter
    def blueprint_file(self, value):
        self._blueprint_file = value

    @property
    def cleanup_required(self):
        return self._cleanup_required

    def verify_all(self):
        self.upload_blueprint()
        self.create_deployment()
        self.install()
        self.verify_installation()
        self.uninstall()
        self.delete_deployment()

    def verify_installation(self):
        self.assert_deployment_events_exist()
        self.assert_deployment_metrics_exist()

    def delete_deployment(self):
        self.logger.info('Deleting deployment...')
        self.manager.client.deployments.delete(self.deployment_id)

    def uninstall(self):
        self.logger.info('Uninstalling deployment...')
        self.cfy.executions.start.uninstall(['-d', self.deployment_id])
        self._cleanup_required = False

    def upload_blueprint(self):
        self._clone_example()
        blueprint_file = self._cloned_to / self.blueprint_file
        self.logger.info('Uploading blueprint: %s [id=%s]',
                         blueprint_file,
                         self.blueprint_id)
        self.manager.client.blueprints.upload(blueprint_file, self.blueprint_id)

    def create_deployment(self):
        self.logger.info(
                'Creating deployment [id=%s] with the following inputs:%s%s',
                self.deployment_id, os.linesep, json.dumps(self.inputs, indent=2))
        self.manager.client.deployments.create(
                self.deployment_id, self.blueprint_id, inputs=self.inputs)
        self.cfy.deployments.list()

    def install(self):
        self.logger.info('Installing deployment...')
        self._cleanup_required = True
        self.cfy.executions.start.install(['-d', self.deployment_id])

    def _clone_example(self):
        if not self._cloned_to:
            self._cloned_to = git_helper.clone(
                    self.REPOSITORY_URL,
                    str(self.tmpdir))

    def cleanup(self):
        if self._cleanup_required:
            self.logger.info('Performing hello world cleanup..')
            self.cfy.executions.start.uninstall(
                    ['-d', self.deployment_id, '-p',
                     'ignore_failure=true', '-f'])

    def assert_deployment_metrics_exist(self):
        self.logger.info('Verifying deployment metrics..')
        influxdb = self.manager.influxdb_client
        try:
            # select monitoring events for deployment from
            # the past 5 seconds. a NameError will be thrown only if NO
            # deployment events exist in the DB regardless of time-span
            # in query.
            influxdb.query('select * from /^{0}\./i '
                           'where time > now() - 5s'
                           .format(self.deployment_id))
        except NameError as e:
            pytest.fail('Monitoring events list for deployment with ID {0} were'
                        ' not found on influxDB. error is: {1}'
                        .format(self.deployment_id, e))

    def assert_deployment_events_exist(self):
        self.logger.info('Verifying deployment events..')
        executions = self.manager.client.executions.list(
                deployment_id=self.deployment_id)
        events, total_events = self.manager.client.events.get(executions[0].id)
        self.assertGreater(len(events), 0,
                           'There are no events for deployment: {0}'.format(
                                   self.deployment_id))


class HelloWorldExample(_AbstractExample):

    REPOSITORY_URL = 'https://github.com/cloudify-cosmo/cloudify-hello-world-example.git'  # noqa

    def __init__(self, *args, **kwargs):
        super(HelloWorldExample, self).__init__(*args, **kwargs)
        self.disable_iptables = False

    @property
    def inputs(self):
        if not self._inputs:
            if self._blueprint_file == 'openstack-blueprint.yaml':
                self._inputs = {
                    'floating_network_id': self.attributes.floating_network_id,
                    'key_pair_name': self.attributes.keypair_name,
                    'private_key_path': self.manager.remote_private_key_path,
                    'flavor': self.attributes.medium_flavor_name,
                    'network_name': self.attributes.network_name
                }
            else:
                self._inputs = {}
        return self._inputs

    def verify_installation(self):
        super(HelloWorldExample, self).verify_installation()
        outputs = self.manager.client.deployments.outputs.get(
                self.deployment_id)['outputs']
        self.logger.info('Deployment outputs: %s%s',
                         os.linesep, json.dumps(outputs, indent=2))
        http_endpoint = outputs['http_endpoint']
        if self.disable_iptables:
            self._disable_iptables(http_endpoint)
        self.assert_webserver_running(http_endpoint)

    @retry(stop_max_attempt_number=3, wait_fixed=10000)
    def _disable_iptables(self, http_endpoint):
        self.logger.info('Disabling iptables on hello world vm..')
        ip = re.findall(r'[0-9]+(?:\.[0-9]+){3}', http_endpoint)[0]
        self.logger.info('Hello world vm IP address is: %s', ip)
        with fabric_context_managers.settings(
                host_string=ip,
                user=self.inputs['agent_user'],
                key_filename=self._ssh_key.private_key_path,
                connections_attempts=3,
                abort_on_prompts=True):
            fabric_api.sudo('sudo service iptables save')
            fabric_api.sudo('sudo service iptables stop')
            fabric_api.sudo('sudo chkconfig iptables off')

    @retry(stop_max_attempt_number=10, wait_fixed=5000)
    def assert_webserver_running(self, http_endpoint):
        self.logger.info(
                'Verifying web server is running on: {0}'.format(http_endpoint))
        server_response = requests.get(http_endpoint, timeout=15)
        if server_response.status_code != 200:
            pytest.fail('Unexpected status code: {}'.format(
                    server_response.status_code))


class NodeCellarExample(_AbstractExample):

    REPOSITORY_URL = 'https://github.com/cloudify-cosmo/cloudify-nodecellar-example.git'  # noqa

    @property
    def inputs(self):
        if not self._inputs:
            if self._blueprint_file == 'openstack-blueprint.yaml':
                self._inputs = {
                    'floating_network_id': self.attributes.floating_network_id,
                    'key_pair_name': self.attributes.keypair_name,
                    'private_key_path': self.manager.remote_private_key_path,
                    'network_name': self.attributes.network_name,
                    'image': self.attributes.ubuntu_14_04_image_name,
                    'flavor': self.attributes.medium_flavor_name,
                    'agent_user': self.attributes.ubuntu_username
                }
            else:
                self._inputs = {}
        return self._inputs

    def verify_installation(self):
        super(NodeCellarExample, self).verify_installation()
        outputs = self.manager.client.deployments.outputs.get(
                self.deployment_id)['outputs']
        self.logger.info('Deployment outputs: %s%s',
                         os.linesep, json.dumps(outputs, indent=2))
        self.assert_nodecellar_working(outputs['endpoint'])
        self.assert_mongodb_collector_data()

    def assert_mongodb_collector_data(self):

        influxdb = self.manager.influxdb_client

        # retrieve some instance id of the mongodb node
        mongo_node_name = 'mongod'
        instance_id = self.manager.client.node_instances.list(
                self.deployment_id, mongo_node_name)[0].id

        try:
            # select metrics from the mongo collector explicitly to verify
            # it is working properly
            query = 'select sum(value) from /{0}\.{1}\.{' \
                    '2}\.mongo_connections_totalCreated/' \
                .format(self.deployment_id, mongo_node_name,
                        instance_id)
            influxdb.query(query)
        except Exception as e:
            pytest.fail('monitoring events for {0} node instance '
                        'with id {1} were not found on influxDB. error is: {2}'
                        .format(mongo_node_name, instance_id, e))

    def assert_nodecellar_working(self, endpoint):
        nodecellar_base_url = 'http://{0}:{1}'.format(endpoint['ip_address'],
                                                      endpoint['port'])
        nodejs_server_page_response = requests.get(nodecellar_base_url)
        self.assertEqual(200, nodejs_server_page_response.status_code,
                         'Failed to get home page of nodecellar app')
        page_title = 'Node Cellar'
        self.assertTrue(page_title in nodejs_server_page_response.text,
                        'Expected to find {0} in web server response: {1}'
                        .format(page_title, nodejs_server_page_response))

        wines_page_response = requests.get(
                '{0}/wines'.format(nodecellar_base_url))
        self.assertEqual(200, wines_page_response.status_code,
                         'Failed to get the wines page on nodecellar app ('
                         'probably means a problem with the connection to '
                         'MongoDB)')

        try:
            wines_json = json.loads(wines_page_response.text)
            if type(wines_json) != list:
                self.fail('Response from wines page is not a JSON list: {0}'
                          .format(wines_page_response.text))

            self.assertGreater(len(wines_json), 0,
                               'Expected at least 1 wine data in nodecellar '
                               'app; json returned on wines page is: {0}'
                               .format(wines_page_response.text))
        except BaseException:
            self.fail('Response from wines page is not a valid JSON: {0}'
                      .format(wines_page_response.text))
