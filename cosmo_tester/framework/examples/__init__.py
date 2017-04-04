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
import uuid
from abc import ABCMeta

import pytest
import testtools

from cosmo_tester.framework import git_helper


class AbstractExample(testtools.TestCase):

    __metaclass__ = ABCMeta

    REPOSITORY_URL = None

    def __init__(self, cfy, manager, attributes, ssh_key, logger, tmpdir,
                 branch=None):
        self.attributes = attributes
        self.logger = logger
        self.manager = manager
        self.cfy = cfy
        self.tmpdir = tmpdir
        self.branch = branch
        self._ssh_key = ssh_key
        self._cleanup_required = False
        self._blueprint_file = None
        self._inputs = None
        self._cloned_to = None
        self.blueprint_id = 'hello-{0}'.format(str(uuid.uuid4()))
        self.deployment_id = self.blueprint_id
        self.verify_metrics = True

    @property
    def blueprint_file(self):
        if not self._blueprint_file:
            raise ValueError('blueprint_file not set')
        return self._blueprint_file

    @blueprint_file.setter
    def blueprint_file(self, value):
        self._blueprint_file = value

    @property
    def blueprint_path(self):
        if not self._cloned_to:
            raise RuntimeError('_cloned_to is not set')
        return self._cloned_to / self.blueprint_file

    @property
    def cleanup_required(self):
        return self._cleanup_required

    @property
    def outputs(self):
        outputs = self.manager.client.deployments.outputs.get(
                self.deployment_id)['outputs']
        self.logger.info('Deployment outputs: %s%s',
                         os.linesep, json.dumps(outputs, indent=2))
        return outputs

    def verify_all(self):
        self.upload_blueprint()
        self.create_deployment()
        self.install()
        self.verify_installation()
        self.uninstall()
        self.delete_deployment()

    def verify_installation(self):
        self.assert_deployment_events_exist()
        if self.verify_metrics:
            self.assert_deployment_metrics_exist()

    def delete_deployment(self):
        self.logger.info('Deleting deployment...')
        self.manager.client.deployments.delete(self.deployment_id)

    def uninstall(self):
        self.logger.info('Uninstalling deployment...')
        self.cfy.executions.start.uninstall(['-d', self.deployment_id])
        self._cleanup_required = False

    def upload_blueprint(self):
        self.clone_example()
        blueprint_file = self._cloned_to / self.blueprint_file
        self.logger.info('Uploading blueprint: %s [id=%s]',
                         blueprint_file,
                         self.blueprint_id)
        self.manager.client.blueprints.upload(
                blueprint_file, self.blueprint_id)

    def create_deployment(self):
        self.logger.info(
                'Creating deployment [id=%s] with the following inputs:%s%s',
                self.deployment_id,
                os.linesep,
                json.dumps(self.inputs, indent=2))
        self.manager.client.deployments.create(
                self.deployment_id, self.blueprint_id, inputs=self.inputs)
        self.cfy.deployments.list()

    def install(self):
        self.logger.info('Installing deployment...')
        self._cleanup_required = True
        try:
            self.cfy.executions.start.install(['-d', self.deployment_id])
        except Exception as e:
            if 'if there is a running system-wide' in e.message:
                self.logger.error('Error on deployment execution: %s', e)
                self.logger.info('Listing executions..')
                self.cfy.executions.list(['-d', self.deployment_id])
                self.cfy.executions.list(['--include-system-workflows'])
            raise

    def clone_example(self):
        if not self._cloned_to:
            self._cloned_to = git_helper.clone(self.REPOSITORY_URL,
                                               str(self.tmpdir),
                                               branch=self.branch)

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
            pytest.fail('Monitoring events list for deployment with ID {0} '
                        'were not found on influxDB. error is: {1}'
                        .format(self.deployment_id, e))

    def assert_deployment_events_exist(self):
        self.logger.info('Verifying deployment events..')
        executions = self.manager.client.executions.list(
                deployment_id=self.deployment_id)
        events, total_events = self.manager.client.events.get(executions[0].id)
        self.assertGreater(len(events), 0,
                           'There are no events for deployment: {0}'.format(
                                   self.deployment_id))
