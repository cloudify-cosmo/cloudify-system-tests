########
# Copyright (c) 2016 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.

import json
import uuid

import pytest

from retrying import retry

from cosmo_tester.framework import util
from cosmo_tester.framework.examples import get_example_deployment
from cosmo_tester.framework.util import set_client_tenant


update_counter = 0


@pytest.fixture(scope='function')
def example_deployment(cfy, image_based_manager, ssh_key, logger,
                       test_config):
    example = get_example_deployment(
        image_based_manager, ssh_key, logger, 'dep_update', test_config)

    yield example
    example.uninstall()


def test_simple_deployment_update(cfy,
                                  image_based_manager,
                                  example_deployment,
                                  tmpdir,
                                  logger):
    example_deployment.upload_and_verify_install()

    modified_blueprint_path = util.get_resource_path(
        'blueprints/compute/example_2_files.yaml'
    )

    logger.info('Updating example deployment...')
    _update_deployment(cfy,
                       image_based_manager,
                       example_deployment.deployment_id,
                       example_deployment.tenant,
                       modified_blueprint_path,
                       tmpdir,
                       skip_reinstall=True)

    logger.info('Checking old files still exist')
    example_deployment.check_files()

    logger.info('Checking new files exist')
    example_deployment.check_files(path='/tmp/test_announcement',
                                   expected_content='I like cake')

    logger.info('Updating deployment to use different path and content')
    _update_deployment(cfy,
                       image_based_manager,
                       example_deployment.deployment_id,
                       example_deployment.tenant,
                       example_deployment.blueprint_file,
                       tmpdir,
                       inputs={'path': '/tmp/new_test',
                               'content': 'Where are the elephants?'})

    logger.info('Checking new files were created')
    example_deployment.check_files(
        path='/tmp/new_test',
        expected_content='Where are the elephants?',
    )
    logger.info('Checking old files were removed')
    # This will look for the originally named files
    example_deployment.check_all_test_files_deleted()

    logger.info('Uninstalling deployment')
    example_deployment.uninstall()
    logger.info('Checking new files were removed')
    example_deployment.check_all_test_files_deleted(path='/tmp/new_test')


def _wait_for_deployment_update_to_finish(func):
    def _update_and_wait_to_finish(cfy,
                                   manager,
                                   deployment_id,
                                   tenant,
                                   *args,
                                   **kwargs):
        func(cfy, manager, deployment_id, tenant, *args, **kwargs)

        @retry(stop_max_attempt_number=10,
               wait_fixed=5000,
               retry_on_result=lambda r: not r)
        def repetitive_check():
            with set_client_tenant(manager, tenant):
                dep_updates_list = manager.client.deployment_updates.list(
                        deployment_id=deployment_id)
                executions_list = manager.client.executions.list(
                        deployment_id=deployment_id,
                        workflow_id='update',
                        _include=['status']
                )
            if len(dep_updates_list) != update_counter:
                return False
            for deployment_update in dep_updates_list:
                if deployment_update.state not in ['failed', 'successful']:
                    return False
            for execution in executions_list:
                if execution['status'] not in ['terminated',
                                               'failed',
                                               'cancelled']:
                    return False
            return True
        repetitive_check()
    return _update_and_wait_to_finish


@_wait_for_deployment_update_to_finish
def _update_deployment(cfy,
                       manager,
                       deployment_id,
                       tenant,
                       blueprint_path,
                       tmpdir,
                       skip_reinstall=False,
                       inputs=None):
    kwargs = {}
    if inputs:
        kwargs['inputs'] = json.dumps(inputs)
    global update_counter
    update_counter += 1
    cfy.deployments.update(deployment_id,
                           blueprint_id='b-{0}'.format(uuid.uuid4()),
                           blueprint_path=blueprint_path,
                           tenant_name=tenant,
                           skip_reinstall=skip_reinstall,
                           **kwargs)
