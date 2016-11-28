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
from threading import Thread

from cosmo_tester.framework.testenv import TestCase
from cosmo_tester.framework.util import create_rest_client


class ScalabilityTest(TestCase):
    MANAGER_IP = '185.98.150.115'
    MANAGER_USERNAME = ''
    MANAGER_PASSWORD = ''

    def test_scalability(self):
        self.cfy.use(
            self.MANAGER_IP,
            manager_username=self.MANAGER_USERNAME,
            manager_password=self.MANAGER_PASSWORD
        )
        self.client = create_rest_client(
            manager_ip=self.MANAGER_IP,
            manager_username=self.MANAGER_USERNAME,
            manager_password=self.MANAGER_PASSWORD
        )

        self.test_done = False

        t1 = Thread(target=self._upload_blueprints, name='Upload')
        t1.daemon = True
        t1.start()

        while not self.test_done:
            self.client.blueprints.list()
            sleep(3)

    def _upload_blueprints(self):
        blueprint_path = self.copy_blueprint('scalability')
        self.blueprint_yaml = blueprint_path / 'blueprint.yaml'
        self.inputs_yaml = blueprint_path / 'inputs.yaml'

        for i in range(3000):
            blueprint_id = uuid4()
            self.cfy.blueprints.upload(
                self.blueprint_yaml,
                blueprint_id=blueprint_id
            )

            if i % 100 == 0:
                deployment_id = '{0}_dep'.format(blueprint_id)

                self.create_deployment(
                    blueprint_id=blueprint_id,
                    deployment_id=deployment_id,
                    inputs=self.inputs_yaml
                )

        self.test_done = True
