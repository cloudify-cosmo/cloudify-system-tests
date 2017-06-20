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

import uuid
import testtools
from retrying import retry
from datetime import datetime
from multiprocessing.pool import ThreadPool as Pool
from cosmo_tester.test_suites.snapshots import snapshot_util
from manager_rest.storage.models_states import ExecutionState


class ResourceCreator(testtools.TestCase):
    def __init__(self, manager, blueprint_example, logger):
        self.logger = logger
        self.client = manager.client
        self.blueprint_example = blueprint_example
        self.blueprint_example.clone_example()

    def upload_blueprints(self, blueprints_count, processes_count):
        """Uploads blueprints simultaneously with a number of processes.
        """
        self.logger.info('Uploading {0} blueprints...'.
                         format(blueprints_count))
        start = datetime.now()
        p = Pool(processes=processes_count)
        p.map(self._upload_blueprint, range(blueprints_count))
        time_passed = (datetime.now() - start).total_seconds()
        self.logger.info('Uploaded {0} blueprints with {1} processes took {2} '
                         'seconds'.format(blueprints_count,
                                          processes_count,
                                          time_passed))
        self.assert_blueprints_count(blueprints_count)

    def _upload_blueprint(self, index):
        blueprint_id = '{0}_{1}'.format(self.blueprint_example.resource_name,
                                        index)
        self.client.blueprints.upload(self.blueprint_example.blueprint_path,
                                      blueprint_id)

    def create_deployments(self, deployments_count, processes_count):
        """Creates deployments simultaneously
        """
        self.logger.info('Creating {0} deployments...'.
                         format(deployments_count))
        start = datetime.now()
        p = Pool(processes=processes_count)
        p.map(self._create_deployment, range(deployments_count))
        time_passed = (datetime.now() - start).total_seconds()

        self.logger.info('Created {0} deployments with {1} processes took {2} '
                         'seconds'.format(
                            deployments_count, processes_count, time_passed))
        self.assert_deployments_count(deployments_count)

    def _create_deployment(self, index):
        blueprint_id = '{0}_{1}'.format(self.blueprint_example.resource_name,
                                        index)

        self.client.deployments.create(blueprint_id,
                                       deployment_id=blueprint_id,
                                       inputs=self.blueprint_example.inputs)

    def create_snapshot(self):
        self.logger.info('Creating snapshot...')
        self._waiting_for_active_executions()
        snapshot_id = str(uuid.uuid4())
        self.client.snapshots.create(snapshot_id, True, True)
        snapshot_util.assert_snapshot_created(snapshot_id, self.client)
        self.logger.info('success')

    def delete_deployments(self, deployments_count, processes_count):
        """Deletes all the deployments and blueprints simultaneously
        """
        self.logger.info('Deleting {0} deployments and blueprints of {1} '
                         'example'.format(
                            deployments_count,
                            self.blueprint_example.resource_name))
        self._waiting_for_active_executions()
        start = datetime.now()
        p = Pool(processes=processes_count)
        p.map(self._delete_deployment, range(deployments_count))
        time_passed = (datetime.now() - start).total_seconds()
        self.logger.info('Deleted {0} deployments and blueprints with {1} '
                         'processes took {2} seconds'.format(deployments_count,
                                                             processes_count,
                                                             time_passed))
        self.assert_blueprints_count(0)
        self.assert_deployments_count(0)

    def _delete_deployment(self, index):
        blueprint_id = '{0}_{1}'.format(self.blueprint_example.resource_name,
                                        index)
        self.client.deployments.delete(blueprint_id)
        self.client.blueprints.delete(blueprint_id)

    @retry(stop_max_attempt_number=3,
           wait_fixed=5000,
           retry_on_result=lambda r: not r)
    def _waiting_for_active_executions(self):
        self.logger.info('Waiting for active executions')
        executions = self.client.executions.list(
            include_system_workflows=True, status=ExecutionState.ACTIVE_STATES)
        return len(executions.items) == 0

    def assert_deployments_count(self, expected_count):
        deployments_list = self.client.deployments.list()
        assert deployments_list.metadata.pagination.total == expected_count

    def assert_blueprints_count(self, expected_count):
        blueprints_list = self.client.blueprints.list()
        assert blueprints_list.metadata.pagination.total == expected_count
