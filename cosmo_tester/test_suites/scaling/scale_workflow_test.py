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

from cosmo_tester.framework.examples.on_manager import OnManagerExample
from cosmo_tester.framework.util import (
    prepare_and_get_test_tenant,
    set_client_tenant,
)


@pytest.fixture(scope='function')
def on_manager_example(cfy, image_based_manager, attributes, ssh_key, tmpdir,
                       logger):
    tenant = prepare_and_get_test_tenant('scale', image_based_manager, cfy)

    image_based_manager.upload_test_plugin(tenant)

    example = OnManagerExample(
        cfy, image_based_manager, attributes, ssh_key, logger, tmpdir,
        tenant=tenant,
    )

    yield example


def _scale(cfy, deployment_id, delta, tenant):
    cfy.executions.start.scale([
        '-d', deployment_id,
        '-p', 'scalable_entity_name=file',
        '-p', 'delta={}'.format(delta),
        '-p', 'scale_compute=true',
        '--tenant-name', tenant])


def _assert_scale(manager, deployment_id, outputs, expected_instances,
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
            on_manager_example.outputs,
            expected_instances=6,
            tenant=on_manager_example.tenant)
    on_manager_example.check_files()

    logger.info('Performing scale in -1..')
    _scale(cfy, on_manager_example.deployment_id, delta=-1,
           tenant=on_manager_example.tenant)
    _assert_scale(
            image_based_manager,
            on_manager_example.deployment_id,
            on_manager_example.outputs,
            expected_instances=4,
            tenant=on_manager_example.tenant)
    on_manager_example.check_files()

    on_manager_example.uninstall()

    # This gets us the full paths, which then allows us to see if the test
    # file prefix is in there.
    # Technically this could collide if the string /tmp/test_file is in there
    # but not actually part of the path, but that's unlikely so we'll tackle
    # that problem when we cause it.
    # Running with sudo to avoid exit status of 1 due to root owned files
    tmp_contents = image_based_manager.run_command('sudo find /tmp').stdout
    assert on_manager_example.inputs['path'] not in tmp_contents
