########
# Copyright (c) 2018-2019 Cloudify Platform Ltd. All rights reserved
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
from cosmo_tester.framework.examples.on_manager import OnManagerExample
from cosmo_tester.framework.util import prepare_and_get_test_tenant


ATTRIBUTES = util.get_attributes()


@pytest.fixture(scope='function')
def fake_vm(cfy, image_based_manager, attributes, ssh_key, logger, tmpdir):
    tenant = prepare_and_get_test_tenant('capability', image_based_manager,
                                         cfy, upload=False)

    example = OnManagerExample(cfy,
                               image_based_manager,
                               attributes,
                               ssh_key,
                               logger,
                               tmpdir,
                               tenant=tenant)

    example.blueprint_file = util.get_resource_path(
        'blueprints/capabilities/fake_vm.yaml'
    )
    example.blueprint_id = 'fake_vm'
    example.deployment_id = 'fake_vm'
    example.inputs = {}
    yield example


@pytest.fixture(scope='function')
def proxied_plugin_file(cfy, image_based_manager, attributes, ssh_key, logger,
                        tmpdir):
    tenant = prepare_and_get_test_tenant('capability', image_based_manager,
                                         cfy, upload=False)

    image_based_manager.upload_test_plugin(tenant)

    example = OnManagerExample(cfy,
                               image_based_manager,
                               attributes,
                               ssh_key,
                               logger,
                               tmpdir,
                               tenant=tenant)
    example.blueprint_file = util.get_resource_path(
        'blueprints/capabilities/capable_file.yaml'
    )
    example.blueprint_id = 'proxied_file'
    example.deployment_id = 'proxied_file'
    example.inputs['tenant'] = tenant
    # We don't need the secret as we won't be sshing to install the agent
    example.create_secret = False
    yield example


def test_capabilities(fake_vm,
                      proxied_plugin_file,
                      logger):
    # We're uploading a blueprint that creates an infrastructure for a VM,
    # and then exposes capabilities, which will be used in the application
    logger.info('Deploying infrastructure blueprint.')
    fake_vm.upload_blueprint()
    fake_vm.create_deployment()
    fake_vm.install()

    logger.info('Deploying application blueprint.')
    # This application relies on capabilities that it gets from the fake_vm,
    # as well as utilizing the new agent proxy ability to connect to an
    # agent of a node installed previously in another deployment (fake_vm)
    proxied_plugin_file.upload_and_verify_install()
    logger.info('File successfully validated.')

    proxied_plugin_file.uninstall()
    fake_vm.uninstall(check_files_are_deleted=False)
