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

from cosmo_tester.framework.cloudify_manager import CloudifyManager
from cosmo_tester.framework import examples


@pytest.fixture(scope='module')
def bootstrap_based_manager(
        request, cfy, ssh_key, module_tmpdir, attributes, logger):
    """Creates a cloudify manager from an image in rackspace OpenStack."""
    manager = CloudifyManager.create_bootstrap_based(
            cfy, ssh_key, module_tmpdir, attributes, logger)

    yield manager

    manager.destroy()


@pytest.fixture(scope='function')
def hello_world(cfy, bootstrap_based_manager, attributes, ssh_key, tmpdir, logger):
    hw = examples.HelloWorldExample(
            cfy, bootstrap_based_manager, attributes, ssh_key, logger, tmpdir)
    hw.blueprint_file = 'openstack-blueprint.yaml'
    yield hw
    if hw.cleanup_required:
        logger.info('Hello world cleanup required..')
        hw.cleanup()


def test_hello_world_on_boostrapped_manager(hello_world, attributes):
    hello_world.inputs.update({
        'agent_user': attributes.centos7_username,
        'image': attributes.centos7_image_name,
    })
    hello_world.verify_all()
