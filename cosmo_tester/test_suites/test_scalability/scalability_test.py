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

from uuid import uuid4
from time import sleep
import multiprocessing
import Queue

from cosmo_tester.framework.testenv import TestCase
from cosmo_tester.framework.util import create_rest_client

MANAGER_IP = '185.98.150.115'
MANAGER_USERNAME = 'admin'
MANAGER_PASSWORD = 'NcM2YizuzatJ'
NUM_OF_BLUEPRINTS = 20
REQUESTS_INTERVAL = 2
CREATE_DEPLOYMENT_COUNT = 2
NUM_OF_PROC = 5


class ScalabilityTest(TestCase):

    def test_scalability(self):
        self.cfy.profiles.use(
            MANAGER_IP,
            manager_username=MANAGER_USERNAME,
            manager_password=MANAGER_PASSWORD
        )
        self.client = create_rest_client(
            manager_ip=MANAGER_IP,
            manager_username=MANAGER_USERNAME,
            manager_password=MANAGER_PASSWORD
        )

        self.q_blueprint_ids = multiprocessing.Queue()
        self.q_deployment_ids = multiprocessing.Queue()
        self.blueprints_counter = 0
        blueprint_path = self.copy_blueprint('scalability')
        self.inputs_yaml = blueprint_path / 'inputs.yaml'

        self.logger.info('Sending HTTP requests in loop for all test run')
        self.logger.info('Uploading {0} blueprints'.format(NUM_OF_BLUEPRINTS))
        self.logger.info('Each {0} blueprints will create deployment'.format(CREATE_DEPLOYMENT_COUNT))

        jobs = []
        for i in range(NUM_OF_PROC):
            p = multiprocessing.Process(name='upload_blueprints', target=self._upload_blueprints)
            jobs.append(p)
            p.start()

        r = multiprocessing.Process(name='send_requests', target=self._send_requests)
        r.start()
        for p in jobs:
            p.join()

        r.terminate()

    def _upload_blueprints(self):
        for i in range(NUM_OF_BLUEPRINTS / NUM_OF_PROC):
            self.blueprints_counter += 1
            blueprint_id = uuid4()
            self.q_blueprint_ids.put(blueprint_id)
            self.cfy.blueprints.upload(
                'cloudify-cosmo/cloudify-nodecellar-example',
                blueprint_filename='openstack-blueprint.yaml',
                blueprint_id=blueprint_id
            )

            if self.blueprints_counter % CREATE_DEPLOYMENT_COUNT == 0:
                deployment_id = '{0}_dep'.format(blueprint_id)
                self.q_deployment_ids.put(deployment_id)
                self.create_deployment(
                    blueprint_id=blueprint_id,
                    deployment_id=deployment_id,
                    inputs=self.inputs_yaml
                )

        # self._clean_manager()

    def _send_requests(self):
        error_count = 0
        while True:
            try:
                self.client.blueprints.list().items
            except Exception:
                error_count += 1
                print Exception.message
            sleep(REQUESTS_INTERVAL)
            if error_count == 3:
                raise Exception

    def _clean_manager(self):
        sleep(60)
        self.logger.info('Cleaning up manager after test...')
        while not self.q_deployment_ids.empty():
            try:
                deployment_id = self.q_deployment_ids.get()
                self.delete_deployment(deployment_id)
            except Queue.Empty:
                break

        while not self.q_blueprint_ids.empty():
            try:
                blueprint_id = self.q_blueprint_ids.get()
                self.delete_blueprint(blueprint_id)
            except Queue.Empty:
                break
