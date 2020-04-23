########
# Copyright (c) 2020 Cloudify Platform Ltd. All rights reserved
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

from cosmo_tester.framework import util
from cosmo_tester.framework.examples import get_example_deployment


@pytest.fixture(scope='function')
def infra(cfy, image_based_manager, ssh_key, logger):
    example = get_example_deployment(
        cfy, image_based_manager, ssh_key, logger, 'test_tenant',
        upload_plugin=False)

    example.blueprint_file = util.get_resource_path(
        'blueprints/component/fake_infra.yaml'
    )
    example.blueprint_id = 'infra'
    example.deployment_id = 'infra'
    example.inputs = {}
    yield example


@pytest.fixture(scope='function')
def app(cfy, image_based_manager, ssh_key, logger):
    example = get_example_deployment(
        cfy, image_based_manager, ssh_key, logger, 'test_tenant')

    example.blueprint_file = util.get_resource_path(
        'blueprints/component/component.yaml'
    )
    example.blueprint_id = 'app'
    example.deployment_id = 'app'
    example.create_secret = False   # don't try to create it twice
    yield example


def test_component(infra, app, logger):
    # We're uploading a blueprint that creates an infrastructure for a VM,
    # and then exposes capabilities, which will be used in the application
    logger.info('Deploying infrastructure blueprint.')
    infra.upload_blueprint()
    # infra.create_deployment()
    # infra.install()

    logger.info('Deploying application blueprint.')

    import pydevd
    pydevd.settrace('192.168.43.16', port=53200, stdoutToServer=True,
                    stderrToServer=True)

    app.upload_and_verify_install()

    app.uninstall()
    # infra.uninstall(check_files_are_deleted=False)






