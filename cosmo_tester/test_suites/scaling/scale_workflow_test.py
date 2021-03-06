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
from cosmo_tester.framework.util import (
    run_blocking_execution,
    set_client_tenant,
)


@pytest.fixture(scope='function')
def on_manager_example(image_based_manager, ssh_key, logger, test_config):
    example = get_example_deployment(
        image_based_manager, ssh_key, logger, 'scale', test_config)

    yield example


def _scale(client, deployment_id, delta, tenant, logger):
    run_blocking_execution(
        client,
        deployment_id,
        'scale',
        logger,
        params={
            'scalable_entity_name': 'file',
            'delta': delta,
            'scale_compute': True,
        },
        tenant=tenant,
    )


def _assert_scale(manager, deployment_id, expected_instances,
                  tenant):
    with set_client_tenant(manager.client, tenant):
        instances = manager.client.node_instances.list(
            deployment_id=deployment_id,
            _include=['id'],
        )
    assert len(instances) == expected_instances


def test_scaling(image_based_manager, on_manager_example, logger):
    on_manager_example.upload_and_verify_install()

    logger.info('Performing scale out +2..')
    _scale(image_based_manager.client, on_manager_example.deployment_id,
           delta=2, tenant=on_manager_example.tenant, logger=logger)
    _assert_scale(
            image_based_manager,
            on_manager_example.deployment_id,
            # 3 lots of (1 vm node, 1 file node, 1 wait node)
            expected_instances=9,
            tenant=on_manager_example.tenant)
    on_manager_example.check_files()

    logger.info('Performing scale in -1..')
    _scale(image_based_manager.client, on_manager_example.deployment_id,
           delta=-1, tenant=on_manager_example.tenant, logger=logger)
    _assert_scale(
            image_based_manager,
            on_manager_example.deployment_id,
            # 2 lots of (1 vm node, 1 file node, 1 wait node)
            expected_instances=6,
            tenant=on_manager_example.tenant)
    on_manager_example.check_files()

    on_manager_example.uninstall()

    on_manager_example.check_all_test_files_deleted()
