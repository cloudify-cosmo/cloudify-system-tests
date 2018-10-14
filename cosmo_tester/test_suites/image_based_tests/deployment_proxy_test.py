########
# Copyright (c) 2018 Cloudify Platform Ltd. All rights reserved
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
from cosmo_tester.framework.fixtures import image_based_manager
from cosmo_tester.framework.examples.hello_world import centos_hello_world


manager = image_based_manager


@pytest.fixture(scope='function')
def infrastructure(cfy, manager, attributes, ssh_key, logger, tmpdir):
    hw = centos_hello_world(cfy,
                            manager,
                            attributes,
                            ssh_key,
                            logger,
                            tmpdir)
    hw.blueprint_file = util.get_resource_path(
        'blueprints/deployment_proxy/infrastructure.yaml'
    )
    hw.blueprint_id = 'os_infra'
    hw.deployment_id = 'os_infra'
    yield hw
    hw.cleanup()


@pytest.fixture(scope='function')
def web_app(cfy, manager, attributes, ssh_key, logger, tmpdir):
    hw = centos_hello_world(cfy,
                            manager,
                            attributes,
                            ssh_key,
                            logger,
                            tmpdir)
    hw.blueprint_file = util.get_resource_path(
        'blueprints/deployment_proxy/web_app.yaml'
    )
    hw.inputs.clear()
    yield hw
    hw.cleanup()


def test_deployment_proxy(cfy,
                          manager,
                          infrastructure,
                          web_app,
                          tmpdir,
                          logger):
    logger.info('Deploying infrastructure blueprint')

    infrastructure.upload_blueprint()
    infrastructure.create_deployment()
    infrastructure.install()

    logger.info('Deploying application blueprint')
    web_app.verify_all()
    logger.info('Webserver successfully validated over proxy')
