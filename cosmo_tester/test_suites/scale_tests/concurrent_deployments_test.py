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

from cosmo_tester.framework import examples
from cosmo_tester.framework.cloudify_manager import CloudifyManager


@pytest.fixture(scope='module')
def manager(
        request, cfy, ssh_key, module_tmpdir, attributes, logger):
    """Creates a cloudify manager from an image in rackspace OpenStack."""
    manager = CloudifyManager.create_image_based(
            cfy, ssh_key, module_tmpdir, attributes, logger)

    with manager.ssh() as fabric_api:
        fabric_api.run('echo "idan moyal"')

    # WORKER_COUNT in /etc/sysconfig/cloudify-restservice
    # set to 1.

    yield manager

    manager.destroy()


@pytest.fixture(scope='function')
def hello_world(cfy, image_based_manager, attributes, ssh_key, tmpdir, logger):
    hw = examples.HelloWorldExample(
            cfy, image_based_manager, attributes, ssh_key, logger, tmpdir)
    hw.blueprint_file = 'openstack-blueprint.yaml'
    yield hw
    if hw.cleanup_required:
        logger.info('Hello world cleanup required..')
        hw.cleanup()


def test_concurrent_delete_deployment(manager, attributes):
    pass
