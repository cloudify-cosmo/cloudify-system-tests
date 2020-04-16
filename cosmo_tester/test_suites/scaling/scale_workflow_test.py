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

from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework.util import set_client_tenant


@pytest.fixture(scope='function')
def on_manager_example(cfy, image_based_manager, ssh_key, logger):
    example = get_example_deployment(
        cfy, image_based_manager, ssh_key, logger, 'scale')

    yield example


def _scale(cfy, deployment_id, delta, tenant):
    cfy.executions.start.scale([
        '-d', deployment_id,
        '-p', 'scalable_entity_name=file',
        '-p', 'delta={}'.format(delta),
        '-p', 'scale_compute=true',
        '--tenant-name', tenant])


def _assert_scale(manager, deployment_id, expected_instances,
                  tenant):
    with set_client_tenant(manager, tenant):
        instances = manager.client.node_instances.list(
            deployment_id=deployment_id,
            _include=['id'],
        )
    assert len(instances) == expected_instances


def test_scaling(cfy, image_based_manager, on_manager_example, logger):
    on_manager_example.upload_and_verify_install()

    logger.info('Performing scale out +2..')
    _scale(cfy, on_manager_example.deployment_id, delta=2,
           tenant=on_manager_example.tenant)
    _assert_scale(
            image_based_manager,
            on_manager_example.deployment_id,
            expected_instances=6,
            tenant=on_manager_example.tenant)
    on_manager_example.check_files()

    logger.info('Performing scale in -1..')
    _scale(cfy, on_manager_example.deployment_id, delta=-1,
           tenant=on_manager_example.tenant)
    _assert_scale(
            image_based_manager,
            on_manager_example.deployment_id,
            expected_instances=4,
            tenant=on_manager_example.tenant)
    on_manager_example.check_files()

    on_manager_example.uninstall()

    on_manager_example.check_all_test_files_deleted()
