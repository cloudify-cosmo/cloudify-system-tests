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
import uuid

import pytest
import requests
from influxdb import InfluxDBClient
from retrying import retry
from fabric import api as fabric_api
from fabric import context_managers as fabric_context_managers

from cosmo_tester.framework import git_helper

CLOUDIFY_HELLO_WORLD_EXAMPLE_URL = 'https://github.com/cloudify-cosmo/cloudify-hello-world-example.git'  # noqa


class HelloWorldExample(object):

    def __init__(self, cfy, manager, attributes, ssh_key, logger, tmpdir):
        self.attributes = attributes
        self.logger = logger
        self.manager = manager
        self.cfy = cfy
        self.tmpdir = tmpdir
        self._ssh_key = ssh_key
        self._cleanup_required = False
        self._deployment_id = None
        self.disable_iptables = False
        self._blueprint_file = None
        self._inputs = None
        self._cloned_to = None
        self._blueprint_id = 'hello-{0}'.format(str(uuid.uuid4()))
        self._deployment_id = self._blueprint_id

    @property
    def blueprint_file(self):
        if not self._blueprint_file:
            raise ValueError('blueprint_file not set')
        return self._blueprint_file

    @blueprint_file.setter
    def blueprint_file(self, value):
        self._blueprint_file = value

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

    def delete_deployment(self):
        self.logger.info('Deleting deployment...')
        self.manager.client.deployments.delete(self._deployment_id)

    def uninstall(self):
        self.logger.info('Uninstalling deployment...')
        self.cfy.executions.start.uninstall(['-d', self._deployment_id])
        self._cleanup_required = False

    def verify_installation(self):
        outputs = self.manager.client.deployments.outputs.get(
                self._deployment_id)['outputs']
        self.logger.info('Deployment outputs: %s%s',
                         os.linesep, json.dumps(outputs, indent=2))
        http_endpoint = outputs['http_endpoint']
        if self.disable_iptables:
            self._disable_iptables(http_endpoint)
        assert_webserver_running(http_endpoint, self.logger)
        assert_events(self._deployment_id, self.manager, self.logger)
        assert_metrics(
                self._deployment_id, self.manager.ip_address, self.logger)

    def install(self):
        self.logger.info('Installing deployment...')
        self._cleanup_required = True
        self.cfy.executions.start.install(['-d', self._deployment_id])

    def create_deployment(self):
        self.logger.info(
                'Creating deployment [id=%s] with the following inputs:%s%s',
                self._deployment_id, os.linesep, json.dumps(self.inputs, indent=2))
        self.manager.client.deployments.create(
                self._deployment_id, self._blueprint_id, inputs=self.inputs)
        self.cfy.deployments.list()

    def upload_blueprint(self):
        self._clone_example()
        blueprint_file = self._cloned_to / self.blueprint_file
        self.logger.info('Uploading blueprint: %s [id=%s]',
                         blueprint_file,
                         self._blueprint_id)
        self.manager.client.blueprints.upload(blueprint_file, self._blueprint_id)

    def _clone_example(self):
        if not self._cloned_to:
            self._cloned_to = git_helper.clone(
                    CLOUDIFY_HELLO_WORLD_EXAMPLE_URL,
                    str(self.tmpdir))

    def cleanup(self):
        self.logger.info('Performing hello world cleanup..')
        self.cfy.executions.start.uninstall(
                ['-d', self._deployment_id, '-p', 'ignore_failure=true', '-f'])

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
def assert_webserver_running(http_endpoint, logger):
    logger.info(
            'Verifying web server is running on: {0}'.format(http_endpoint))
    server_response = requests.get(http_endpoint, timeout=15)
    if server_response.status_code != 200:
        pytest.fail('Unexpected status code: {}'.format(
                server_response.status_code))


def assert_metrics(deployment_id, influx_host_ip, logger):
    logger.info('Verifying deployment metrics..')
    influx_client = InfluxDBClient(influx_host_ip, 8086,
                                   'root', 'root', 'cloudify')
    try:
        # select monitoring events for deployment from
        # the past 5 seconds. a NameError will be thrown only if NO
        # deployment events exist in the DB regardless of time-span
        # in query.
        influx_client.query('select * from /^{0}\./i '
                            'where time > now() - 5s'
                            .format(deployment_id))
    except NameError as e:
        pytest.fail('Monitoring events list for deployment with ID {0} were'
                    ' not found on influxDB. error is: {1}'
                    .format(deployment_id, e))


def assert_events(deployment_id, manager, logger):
    logger.info('Verifying deployment events..')
    executions = manager.client.executions.list(deployment_id=deployment_id)
    events, total_events = manager.client.events.get(executions[0].id)
    assert len(events) > 0, 'There are no events for deployment: {0}'.format(
            deployment_id)
