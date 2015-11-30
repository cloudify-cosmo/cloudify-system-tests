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

from cosmo_tester.test_suites.backwards.test_nodecellar_backwards_compatibility\
    .nodecellar_backwards_compatibility_test_base import \
    NodecellarNackwardsCompatibilityTestBase
from cosmo_tester.test_suites.test_blueprints.nodecellar_test import \
    OpenStackNodeCellarTestBase


RABBITMQ_USERNAME_KEY = 'rabbitmq_username'
RABBITMQ_PASSWORD_KEY = 'rabbitmq_password'
RABBITMQ_USERNAME_VALUE = 'guest'
RABBITMQ_PASSWORD_VALUE = 'guest'


class OldVersionNodeCellarTest(OpenStackNodeCellarTestBase,
                               NodecellarNackwardsCompatibilityTestBase):

    # Nodecellar test using the 3.1 version blueprint
    def test_old_version_openstack_nodecellar(self):
        self.setup_manager()
        self._test_openstack_nodecellar('openstack-blueprint.yaml')

    def get_inputs(self):

        return {
            'image': self.env.ubuntu_trusty_image_id,
            'flavor': self.env.small_flavor_id,
            'agent_user': 'ubuntu'
        }

    @property
    def repo_branch(self):
        return 'tags/3.1'

    def get_manager_blueprint_inputs_override(self):
        # 3.1 diamond plugin is hard coded to use guest:guest
        # no need for 'install_python_compilers' because this
        # only applies for a later version of openstack clients
        # that is not used in the 3.1 blueprint
        return {
            RABBITMQ_USERNAME_KEY: RABBITMQ_USERNAME_VALUE,
            RABBITMQ_PASSWORD_KEY: RABBITMQ_PASSWORD_VALUE
        }
