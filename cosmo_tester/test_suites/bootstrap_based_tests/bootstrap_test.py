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

import pytest

from cosmo_tester.framework.fixtures import bootstrap_based_manager
from cosmo_tester.framework.examples.hello_world import HelloWorldExample
from cosmo_tester.framework.util import get_test_tenant, is_community


manager = bootstrap_based_manager


@pytest.fixture(scope='function')
def hello_worlds(cfy, manager, attributes, ssh_key, tmpdir,
                 logger):
    tenant1 = get_test_tenant('hello1', manager, cfy)
    tenant2 = get_test_tenant('hello2', manager, cfy)
    hellos = [
        HelloWorldExample(
            cfy, manager, attributes, ssh_key, logger, tmpdir,
            tenant=tenant1, suffix='first',
        ),
    ]

    if not is_community():
        hellos.append(
            HelloWorldExample(
                cfy, manager, attributes, ssh_key, logger, tmpdir,
                tenant=tenant2,
            ),
        )

    for hello in hellos:
        hello.blueprint_file = 'openstack-blueprint.yaml'
        hello.inputs.update({
            'agent_user': attributes.centos_7_username,
            'image': attributes.centos_7_image_name,
        })
    yield hellos
    for hello in hellos:
        hello.cleanup()


def test_manager_bootstrap_and_deployment(hello_worlds, attributes):
    for hello in hello_worlds:
        hello.verify_all()
